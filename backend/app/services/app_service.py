from __future__ import annotations

import hashlib
import json
import secrets
import uuid
from dataclasses import asdict
from datetime import date, datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException, Response, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..core.config import get_settings
from ..core.metrics import doses_recorded_total, sync_failures_total
from ..core.security import create_access_token, create_refresh_token_value, hash_password, hash_token, require_role, verify_password
from ..models import Child, ConflictReviewItem, Consent, Dose, DoseSource, Grievance, OtpChallenge, RefreshToken, Role, SyncBatch, SyncChangeLog, User
from ..repositories.main import MainRepository
from ..schemas.api import ChildCreate, ConsentCreate, GrievanceCreate, LoginRequest, OtpRequest, OtpVerify, RefreshRequest, SyncPush, UserCreate
from ..schemas.query import ListQuery
from .audit import audit_child_access
from .analytics import AnalyticsFilters, manager_dashboard, simulated_external_register_csv
from .cache import LEADERBOARD_CACHE_KEY, MANAGER_DASHBOARD_CACHE_KEY, get_json, invalidate_analytics_cache, set_json
from .cards import vaccination_card_pdf
from .crypto import decrypt_phone, decrypt_text, encrypt_phone, encrypt_text, masked_phone
from .event_bus import process_outbox, publish_dose_recorded
from .gamification import child_progress as gamified_child_progress
from .gamification import village_leaderboard as gamified_village_leaderboard
from .notifications import process_inbound_message
from .responsible_design import caregiver_export, delete_caregiver_data, run_retention_job
from .schedule import due_doses, next_visit, overdue_doses, schedule_windows


class AppService:
    def __init__(self, db: Session) -> None:
        self.db = db
        self.repo = MainRepository(db)

    def token_for_user_id(self, user_id: int) -> dict[str, str]:
        user = self.repo.get_user(user_id)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        return self._issue_token_pair(user)

    def login(self, payload: LoginRequest) -> dict[str, str]:
        user = None
        for candidate in self.repo.users():
            if decrypt_phone(candidate.phone) == payload.phone:
                user = candidate
                break
        if user is None:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or password")
        self._ensure_not_locked(user)
        if not verify_password(payload.password, user.pw_hash):
            self._record_failed_login(user)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or password")
        user.failed_login_count = 0
        user.locked_until = None
        self.db.commit()
        return self._issue_token_pair(user)

    def refresh(self, payload: RefreshRequest) -> dict[str, str]:
        token_hash = hash_token(payload.refresh_token)
        token_row = self.db.scalar(
            select(RefreshToken).where(
                RefreshToken.token_hash == token_hash,
                RefreshToken.revoked_at.is_(None),
            )
        )
        if token_row is None or token_row.expires_at < datetime.utcnow():
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        user = self.repo.get_user(token_row.user_id)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid refresh token")
        new_value = create_refresh_token_value()
        new_hash = hash_token(new_value)
        token_row.revoked_at = datetime.utcnow()
        token_row.replaced_by_hash = new_hash
        self.db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=new_hash,
                family_id=token_row.family_id,
                expires_at=datetime.utcnow() + timedelta(days=get_settings().refresh_token_days),
            )
        )
        self.db.commit()
        return {"access_token": create_access_token(user), "refresh_token": new_value, "token_type": "bearer"}

    def logout(self, payload: RefreshRequest) -> dict[str, object]:
        token_hash = hash_token(payload.refresh_token)
        token_row = self.db.scalar(select(RefreshToken).where(RefreshToken.token_hash == token_hash))
        if token_row is not None and token_row.revoked_at is None:
            token_row.revoked_at = datetime.utcnow()
            self.db.commit()
        return {"revoked": True}

    def request_otp(self, payload: OtpRequest) -> dict[str, object]:
        user = self._user_by_phone(payload.phone)
        if user is None:
            raise HTTPException(status_code=404, detail="User not found")
        self._ensure_not_locked(user)
        code = "%06d" % secrets.randbelow(1_000_000)
        self.db.add(
            OtpChallenge(
                user_id=user.id,
                code_hash=hash_password(code),
                expires_at=datetime.utcnow() + timedelta(minutes=get_settings().otp_expiry_minutes),
            )
        )
        self.db.commit()
        return {"otp_sent": True, "demo_code": code}

    def verify_otp(self, payload: OtpVerify) -> dict[str, str]:
        user = self._user_by_phone(payload.phone)
        if user is None:
            raise HTTPException(status_code=401, detail="Invalid OTP")
        self._ensure_not_locked(user)
        challenge = self.db.scalar(
            select(OtpChallenge)
            .where(OtpChallenge.user_id == user.id, OtpChallenge.consumed_at.is_(None))
            .order_by(OtpChallenge.created_at.desc(), OtpChallenge.id.desc())
        )
        settings = get_settings()
        if challenge is None or challenge.expires_at < datetime.utcnow() or challenge.attempts >= settings.otp_max_attempts:
            raise HTTPException(status_code=401, detail="Invalid OTP")
        challenge.attempts += 1
        if not verify_password(payload.code, challenge.code_hash):
            if challenge.attempts >= settings.otp_max_attempts:
                self._record_failed_login(user)
            self.db.commit()
            raise HTTPException(status_code=401, detail="Invalid OTP")
        challenge.consumed_at = datetime.utcnow()
        user.failed_login_count = 0
        user.locked_until = None
        self.db.commit()
        return self._issue_token_pair(user)

    def create_user(self, payload: UserCreate, actor: User) -> dict[str, object]:
        require_role(actor, Role.admin)
        password_hash = payload.pw_hash or (hash_password(payload.password) if payload.password else "")
        if not password_hash:
            raise HTTPException(status_code=400, detail="Password is required")
        user = User(
            role=payload.role,
            name=encrypt_text(payload.name) if payload.role == Role.caregiver else payload.name,
            phone=encrypt_phone(payload.phone),
            village_id=payload.village_id,
            pw_hash=password_hash,
            preferred_language=payload.preferred_language,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user_public(user, include_phone=True)

    def _issue_token_pair(self, user: User) -> dict[str, str]:
        refresh_value = create_refresh_token_value()
        self.db.add(
            RefreshToken(
                user_id=user.id,
                token_hash=hash_token(refresh_value),
                family_id=uuid.uuid4().hex,
                expires_at=datetime.utcnow() + timedelta(days=get_settings().refresh_token_days),
            )
        )
        self.db.commit()
        return {"access_token": create_access_token(user), "refresh_token": refresh_value, "token_type": "bearer"}

    def _ensure_not_locked(self, user: User) -> None:
        if user.locked_until is not None and user.locked_until > datetime.utcnow():
            raise HTTPException(status_code=423, detail="Account locked")

    def _record_failed_login(self, user: User) -> None:
        settings = get_settings()
        user.failed_login_count += 1
        if user.failed_login_count >= settings.login_lockout_threshold:
            user.locked_until = datetime.utcnow() + timedelta(minutes=settings.login_lockout_minutes)
        self.db.commit()

    def _user_by_phone(self, phone: str) -> Optional[User]:
        for candidate in self.repo.users():
            if decrypt_phone(candidate.phone) == phone:
                return candidate
        return None

    def list_users(self, actor: User, options: ListQuery | None = None) -> List[dict[str, object]]:
        require_role(actor, Role.admin)
        return [user_public(user, include_phone=True) for user in self.repo.users(options)]

    def list_villages(self, options: ListQuery | None = None) -> List[dict[str, object]]:
        return [{"id": village.id, "block": village.block, "district": village.district} for village in self.repo.villages(options)]

    def list_schedule(self, options: ListQuery | None = None) -> List[dict[str, object]]:
        return [
            {
                "vaccine_code": row.vaccine_code,
                "name": row.name,
                "age_due_days": row.age_due_days,
                "window_days": row.window_days,
                "endemic_only": row.endemic_only,
            }
            for row in self.repo.schedule_rows(options)
        ]

    def demo_summary(self) -> dict[str, int]:
        return self.repo.counts()

    def capture_consent(self, payload: ConsentCreate, actor: User) -> dict[str, object]:
        if actor.role == Role.caregiver and actor.id != payload.guardian_id:
            raise HTTPException(status_code=403, detail="Caregiver can consent only for self")
        if actor.role not in {Role.caregiver, Role.admin}:
            raise HTTPException(status_code=403, detail="Only guardian or admin can capture consent")
        consent = Consent(guardian_id=payload.guardian_id, purpose=payload.purpose, granted_at=datetime.utcnow())
        self.db.add(consent)
        self.db.commit()
        self.db.refresh(consent)
        return {"id": consent.id, "guardian_id": consent.guardian_id, "purpose": consent.purpose, "granted_at": consent.granted_at}

    def withdraw_consent(self, consent_id: int, actor: User) -> dict[str, object]:
        consent = self.repo.get_consent(consent_id)
        if consent is None:
            raise HTTPException(status_code=404, detail="Consent not found")
        if actor.role == Role.caregiver and actor.id != consent.guardian_id:
            raise HTTPException(status_code=403, detail="Caregiver can withdraw only own consent")
        if actor.role not in {Role.caregiver, Role.admin}:
            raise HTTPException(status_code=403, detail="Only guardian or admin can withdraw consent")
        consent.withdrawn_at = datetime.utcnow()
        self.db.commit()
        return {"id": consent.id, "withdrawn_at": consent.withdrawn_at}

    def create_child(self, payload: ChildCreate, actor: User) -> dict[str, object]:
        if actor.role == Role.caregiver and actor.id != payload.guardian_id:
            raise HTTPException(status_code=403, detail="Caregiver can store only own child")
        if actor.role == Role.asha and actor.village_id != payload.village_id:
            raise HTTPException(status_code=403, detail="ASHA can store children only in assigned village")
        if actor.role == Role.manager:
            raise HTTPException(status_code=403, detail="Managers cannot store child records")
        if self.repo.active_consent(payload.guardian_id, "store_child") is None:
            raise HTTPException(status_code=400, detail="Guardian consent required before storing child")
        child = Child(**payload.model_dump())
        self.db.add(child)
        self.db.flush()
        audit_child_access(self.db, actor.id, "write", child.id, "store child with guardian consent")
        self.db.commit()
        self.db.refresh(child)
        return child_public(child)

    def list_children(self, actor: User, options: ListQuery | None = None) -> List[dict[str, object]]:
        if actor.role == Role.manager:
            return self.repo.aggregated_children(options)
        children = self.repo.children_for_actor(actor, options)
        for child in children:
            audit_child_access(self.db, actor.id, "read", child.id, "list children")
        self.db.commit()
        return [child_public(child) for child in children]

    def get_child(self, child_id: int, actor: User) -> dict[str, object]:
        child = self.accessible_child(child_id, actor)
        audit_child_access(self.db, actor.id, "read", child.id, "read child")
        self.db.commit()
        return child_public(child)

    def child_schedule(self, child_id: int, actor: User) -> dict[str, object]:
        child = self.accessible_child(child_id, actor)
        audit_child_access(self.db, actor.id, "read", child.id, "read child schedule")
        current_day = date.today()
        self.db.commit()
        return {
            "child_id": child.id,
            "as_of": current_day.isoformat(),
            "schedule": [asdict(window) for window in schedule_windows(child, current_day)],
            "due": [asdict(window) for window in due_doses(child, current_day)],
            "overdue": [asdict(window) for window in overdue_doses(child, current_day)],
            "next_visit": asdict(next_visit(child)),
        }

    def child_progress(self, child_id: int, actor: User) -> dict[str, object]:
        child = self.accessible_child(child_id, actor)
        audit_child_access(self.db, actor.id, "read", child.id, "read child progress")
        result = asdict(gamified_child_progress(self.db, child))
        self.db.commit()
        return result

    def blank_card_pdf(self, actor: User) -> Response:
        if actor.role == Role.manager:
            raise HTTPException(status_code=403, detail="Managers cannot print child-level cards")
        return Response(
            content=vaccination_card_pdf(self.db, None),
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=teeka-yatra-blank-card.pdf"},
        )

    def child_card_pdf(self, child_id: int, actor: User) -> Response:
        child = self.accessible_child(child_id, actor)
        audit_child_access(self.db, actor.id, "read", child.id, "print vaccination card")
        content = vaccination_card_pdf(self.db, child)
        self.db.commit()
        return Response(
            content=content,
            media_type="application/pdf",
            headers={"Content-Disposition": "inline; filename=teeka-yatra-child-%s-card.pdf" % child.id},
        )

    def delete_my_data(self, actor: User) -> dict[str, object]:
        require_role(actor, Role.caregiver)
        child_ids = delete_caregiver_data(self.db, actor)
        self.db.commit()
        return {"deleted_child_ids": child_ids}

    def export_my_data(self, actor: User) -> dict[str, object]:
        require_role(actor, Role.caregiver)
        payload = caregiver_export(self.db, actor)
        self.db.commit()
        return payload

    def create_grievance(self, payload: GrievanceCreate, actor: User) -> dict[str, object]:
        guardian_id: Optional[int] = None
        if actor.role == Role.caregiver:
            guardian_id = actor.id
            if payload.child_id is not None:
                self.accessible_child(payload.child_id, actor)
        elif actor.role == Role.asha and payload.child_id is not None:
            self.accessible_child(payload.child_id, actor)
        elif actor.role == Role.manager:
            raise HTTPException(status_code=403, detail="Managers cannot file individual grievances")
        grievance = Grievance(
            guardian_id=guardian_id,
            child_id=payload.child_id,
            category=payload.category,
            message=payload.message,
            contact_preference=payload.contact_preference,
        )
        self.db.add(grievance)
        self.db.commit()
        self.db.refresh(grievance)
        return grievance_public(grievance)

    def list_grievances(self, actor: User, options: ListQuery | None = None) -> List[dict[str, object]]:
        require_role(actor, Role.admin)
        return [grievance_public(row) for row in self.repo.grievances(options)]

    def data_retention_job(self, actor: User) -> dict[str, int]:
        require_role(actor, Role.admin)
        return asdict(run_retention_job(self.db, date.today()))

    def village_leaderboard(self, actor: User, options: ListQuery | None = None) -> List[dict[str, object]]:
        if actor.role == Role.caregiver:
            raise HTTPException(status_code=403, detail="Caregivers cannot view leaderboards")
        options = options or ListQuery(sort="points", order="desc")
        cache_key = "%s:%s:%s:%s:%s" % (LEADERBOARD_CACHE_KEY, options.page, options.page_size, options.sort, options.order)
        cached = get_json(cache_key)
        if isinstance(cached, list):
            return cached
        payload = [asdict(row) for row in gamified_village_leaderboard(self.db)]
        payload = sorted(payload, key=lambda item: item.get(options.sort, item.get("points", 0)), reverse=options.descending or options.sort == "points")
        payload = payload[options.offset : options.offset + options.limit]
        set_json(cache_key, payload)
        return payload

    def manager_analytics(
        self,
        actor: User,
        block: Optional[str] = None,
        district: Optional[str] = None,
        start_date: Optional[date] = None,
        end_date: Optional[date] = None,
        page: int = 1,
        page_size: int = 50,
    ) -> dict[str, object]:
        require_role(actor, Role.manager, Role.admin)
        filters = AnalyticsFilters(block=block, district=district, start_date=start_date, end_date=end_date, page=page, page_size=page_size)
        cache_key = "%s:%s:%s:%s:%s:%s:%s" % (MANAGER_DASHBOARD_CACHE_KEY, block, district, start_date, end_date, page, page_size)
        cached = get_json(cache_key)
        if isinstance(cached, dict):
            return cached
        payload = manager_dashboard(self.db, date.today(), simulated_external_register_csv(), filters)
        set_json(cache_key, payload)
        return payload

    def job_status(self, actor: User) -> dict[str, object]:
        require_role(actor, Role.admin)
        return self.repo.job_status()

    def feature_phone_sim(self) -> str:
        items = "\n".join(
            [
                "<li><span>%s</span><b>%s</b><p>%s</p></li>"
                % (log.channel.value.upper(), log.sent_at.strftime("%d %b %H:%M"), _escape_html(log.message))
                for log in self.repo.notification_logs()
            ]
        )
        if not items:
            items = "<li><span>SMS</span><b>No messages yet</b><p>Run the reminder scheduler to populate this inbox.</p></li>"
        return sim_html(items)

    def sim_inbound(self, phone: str, message: str) -> dict[str, object]:
        return {"processed": process_inbound_message(self.db, phone, message)}

    def sim_inbound_html(self, phone: str, message: str) -> str:
        processed = process_inbound_message(self.db, phone, message)
        status_text = "STOP processed" if processed else "No matching opt-out was processed"
        return "<!doctype html><title>Teeka Yatra Sim</title><p>%s.</p><p><a href='/sim'>Back to inbox</a></p>" % _escape_html(status_text)

    def sync_push(self, payload: SyncPush, actor: User, idempotency_key: str) -> dict[str, object]:
        if actor.role not in {Role.asha, Role.admin}:
            raise HTTPException(status_code=403, detail="Only ASHAs and admins can push offline sync batches")
        request_hash = _sync_request_hash(payload)
        existing_batch = self.repo.sync_batch(actor.id, idempotency_key)
        if existing_batch is not None:
            if existing_batch.request_hash != request_hash:
                raise HTTPException(status_code=409, detail="Idempotency-Key was already used with a different payload")
            return json.loads(existing_batch.response_json)

        results: List[dict[str, object]] = []
        accepted: List[str] = []
        duplicates: List[str] = []
        conflicts: List[dict[str, object]] = []
        for child_update in payload.children:
            child_result: dict[str, object] = {"type": "child", "id": child_update.id}
            try:
                child = self.accessible_child(child_update.id, actor)
            except HTTPException as exc:
                child_result.update({"status": "rejected", "reason": str(exc.detail)})
                results.append(child_result)
                continue
            audit_child_access(self.db, actor.id, "write", child.id, "sync child update")
            if child.client_updated_at is None or child_update.client_updated_at >= child.client_updated_at:
                if child_update.opt_in_sms is not None:
                    child.opt_in_sms = child_update.opt_in_sms
                if child_update.opt_in_ivr is not None:
                    child.opt_in_ivr = child_update.opt_in_ivr
                if child_update.opt_in_app is not None:
                    child.opt_in_app = child_update.opt_in_app
                child.client_updated_at = child_update.client_updated_at
                self.db.flush()
                _append_change(self.db, "child", child.id, child.id, child.village_id, "upsert", child_public(child))
                child_result["status"] = "accepted"
            else:
                child.conflict_flag = True
                conflict = {"type": "child_out_of_order", "child_id": child.id}
                _queue_conflict(self.db, child, None, None, "child_out_of_order", conflict)
                conflicts.append(conflict)
                child_result.update({"status": "conflict", "reason": "server has newer child data"})
            results.append(child_result)
        for incoming in payload.doses:
            item: dict[str, object] = {"type": "dose", "client_uuid": incoming.client_uuid, "child_id": incoming.child_id, "vaccine_code": incoming.vaccine_code}
            try:
                child = self.accessible_child(incoming.child_id, actor)
                source = DoseSource(incoming.source)
            except ValueError:
                item.update({"status": "rejected", "reason": "invalid source"})
                results.append(item)
                continue
            except HTTPException as exc:
                item.update({"status": "rejected", "reason": str(exc.detail)})
                results.append(item)
                continue
            if self.repo.get_dose_by_uuid(incoming.client_uuid) is not None:
                duplicates.append(incoming.client_uuid)
                item["status"] = "duplicate"
                results.append(item)
                continue
            existing_dose = self.repo.get_child_vaccine_dose(incoming.child_id, incoming.vaccine_code)
            if existing_dose is not None:
                existing_dose.conflict_flag = True
                conflict = {
                    "type": "dose_conflict",
                    "client_uuid": incoming.client_uuid,
                    "child_id": incoming.child_id,
                    "vaccine_code": incoming.vaccine_code,
                }
                _queue_conflict(self.db, child, incoming.vaccine_code, incoming.client_uuid, "dose_conflict", conflict)
                conflicts.append(conflict)
                item.update({"status": "conflict", "reason": "dose already exists for child and vaccine"})
                results.append(item)
                continue
            dose = Dose(
                child_id=incoming.child_id,
                vaccine_code=incoming.vaccine_code,
                given_on=incoming.given_on,
                batch_no=incoming.batch_no,
                session_id=incoming.session_id,
                recorded_by=actor.id,
                source=source,
                synced_at=datetime.utcnow(),
                client_uuid=incoming.client_uuid,
                client_updated_at=incoming.client_updated_at,
            )
            self.db.add(dose)
            self.db.flush()
            publish_dose_recorded(self.db, dose, paper_card_updated=incoming.source == "paper")
            audit_child_access(self.db, actor.id, "write", child.id, "sync dose")
            _append_change(self.db, "dose", dose.id, child.id, child.village_id, "insert", dose_public(dose))
            accepted.append(incoming.client_uuid)
            item["status"] = "accepted"
            item["dose_id"] = dose.id
            results.append(item)
        response = {
            "accepted": accepted,
            "duplicates": duplicates,
            "conflicts": conflicts,
            "rejected": [item for item in results if item.get("status") == "rejected"],
            "results": results,
        }
        if accepted:
            doses_recorded_total.inc(len(accepted))
        for item in response["rejected"]:
            sync_failures_total.labels(str(item.get("reason", "rejected"))[:80]).inc()
        for conflict in conflicts:
            sync_failures_total.labels(str(conflict.get("type", "conflict"))[:80]).inc()
        self.db.add(SyncBatch(actor_id=actor.id, idempotency_key=idempotency_key, request_hash=request_hash, response_json=json.dumps(response, default=str)))
        self.db.commit()
        if accepted:
            invalidate_analytics_cache()
            try:
                process_outbox(self.db)
                self.db.commit()
            except Exception:
                self.db.commit()
        return response

    def sync_pull(self, cursor: int, actor: User) -> dict[str, object]:
        if actor.role == Role.manager:
            return {"children": self.repo.aggregated_children(), "doses": [], "conflicts": [], "changes": [], "next_cursor": cursor}
        children = self.repo.children_for_actor(actor)
        changes = self.repo.changes_for_actor(actor, cursor)
        for child in children:
            audit_child_access(self.db, actor.id, "read", child.id, "sync pull")
        self.db.commit()
        next_cursor = max([cursor] + [change.cursor for change in changes])
        return {
            "children": [child_public(child) | {"client_updated_at": child.client_updated_at, "conflict_flag": child.conflict_flag} for child in children],
            "doses": [json.loads(change.payload) for change in changes if change.entity_type == "dose"],
            "changes": [change_public(change) for change in changes],
            "conflicts": conflict_rows(children, []),
            "next_cursor": next_cursor,
            "server_time": datetime.utcnow().isoformat(),
        }

    def conflict_review_queue(self, actor: User, options: ListQuery | None = None) -> List[dict[str, object]]:
        require_role(actor, Role.asha, Role.admin)
        return [
            {
                "id": item.id,
                "child_id": item.child_id,
                "village_id": item.village_id,
                "vaccine_code": item.vaccine_code,
                "client_uuid": item.client_uuid,
                "conflict_type": item.conflict_type,
                "status": item.status.value,
                "details": json.loads(item.details),
                "created_at": item.created_at,
            }
            for item in self.repo.conflict_review_queue(actor, options)
        ]

    def accessible_child(self, child_id: int, actor: User) -> Child:
        child = self.repo.get_child(child_id)
        if child is None:
            raise HTTPException(status_code=404, detail="Child not found")
        if actor.role == Role.caregiver and child.guardian_id != actor.id:
            raise HTTPException(status_code=403, detail="Child not accessible")
        if actor.role == Role.asha and child.village_id != actor.village_id:
            raise HTTPException(status_code=403, detail="Child not in assigned village")
        if actor.role == Role.manager:
            raise HTTPException(status_code=403, detail="Managers can view aggregated data only")
        return child


def user_public(user: User, include_phone: bool) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": user.id,
        "role": user.role.value,
        "name": decrypt_text(user.name),
        "village_id": user.village_id,
        "preferred_language": user.preferred_language,
    }
    if include_phone:
        payload["phone"] = masked_phone(user.phone)
    return payload


def child_public(child: Child) -> dict[str, object]:
    return {
        "id": child.id,
        "dob": child.dob,
        "sex": child.sex.value,
        "village_id": child.village_id,
        "guardian_id": child.guardian_id,
        "asha_id": child.asha_id,
        "opt_in_sms": child.opt_in_sms,
        "opt_in_ivr": child.opt_in_ivr,
        "opt_in_app": child.opt_in_app,
    }


def dose_public(dose: Dose) -> dict[str, object]:
    return {
        "id": dose.id,
        "client_uuid": dose.client_uuid,
        "child_id": dose.child_id,
        "vaccine_code": dose.vaccine_code,
        "given_on": dose.given_on,
        "batch_no": dose.batch_no,
        "session_id": dose.session_id,
        "source": dose.source.value,
        "synced_at": dose.synced_at,
        "client_updated_at": dose.client_updated_at,
        "conflict_flag": dose.conflict_flag,
    }


def change_public(change: SyncChangeLog) -> dict[str, object]:
    return {
        "cursor": change.cursor,
        "entity_type": change.entity_type,
        "entity_id": change.entity_id,
        "child_id": change.child_id,
        "operation": change.operation,
        "payload": json.loads(change.payload),
        "created_at": change.created_at,
    }


def grievance_public(grievance: Grievance) -> dict[str, object]:
    return {
        "id": grievance.id,
        "guardian_id": grievance.guardian_id,
        "child_id": grievance.child_id,
        "category": grievance.category,
        "message": grievance.message,
        "contact_preference": grievance.contact_preference,
        "status": grievance.status,
        "created_at": grievance.created_at,
    }


def conflict_rows(children: List[Child], doses: List[Dose]) -> List[dict[str, object]]:
    rows: List[dict[str, object]] = []
    for child in children:
        if child.conflict_flag:
            rows.append({"type": "child", "child_id": child.id})
    for dose in doses:
        if dose.conflict_flag:
            rows.append({"type": "dose", "dose_id": dose.id, "child_id": dose.child_id})
    return rows


def _sync_request_hash(payload: SyncPush) -> str:
    body = payload.model_dump(mode="json")
    return hashlib.sha256(json.dumps(body, sort_keys=True, separators=(",", ":")).encode("utf-8")).hexdigest()


def _append_change(
    db: Session,
    entity_type: str,
    entity_id: int,
    child_id: int,
    village_id: int,
    operation: str,
    payload: dict[str, object],
) -> None:
    db.add(
        SyncChangeLog(
            entity_type=entity_type,
            entity_id=entity_id,
            child_id=child_id,
            village_id=village_id,
            operation=operation,
            payload=json.dumps(payload, default=str),
        )
    )


def _queue_conflict(
    db: Session,
    child: Child,
    vaccine_code: Optional[str],
    client_uuid: Optional[str],
    conflict_type: str,
    details: dict[str, object],
) -> None:
    db.add(
        ConflictReviewItem(
            child_id=child.id,
            village_id=child.village_id,
            vaccine_code=vaccine_code,
            client_uuid=client_uuid,
            conflict_type=conflict_type,
            details=json.dumps(details, default=str),
        )
    )


def _escape_html(value: str) -> str:
    return value.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def sim_html(items: str) -> str:
    return """
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>Teeka Yatra Feature Phone Sim</title>
  <style>
    body { margin: 0; min-height: 100vh; display: grid; place-items: center; background: #f6f7ef; font-family: Arial, sans-serif; color: #17231d; }
    main { width: min(360px, 92vw); border: 12px solid #27312b; border-radius: 28px; background: #dce8d4; box-shadow: 0 22px 60px rgba(0,0,0,.22); overflow: hidden; }
    header { background: #17231d; color: #fff; padding: 14px 18px; display: flex; justify-content: space-between; font-weight: 700; }
    ol { list-style: none; padding: 12px; margin: 0; display: grid; gap: 10px; max-height: 560px; overflow: auto; }
    li { background: #fbfff7; border: 2px solid #91a488; border-radius: 8px; padding: 10px; }
    span { display: inline-block; background: #0f766e; color: white; border-radius: 4px; padding: 2px 6px; font-size: 12px; margin-right: 6px; }
    b { font-size: 13px; }
    p { margin: 8px 0 0; line-height: 1.35; font-size: 15px; }
    form { display: grid; gap: 8px; padding: 12px; border-top: 2px solid #91a488; background: #eef6e8; }
    input, button { min-height: 42px; font-size: 16px; border-radius: 6px; border: 1px solid #5d6f60; padding: 0 10px; }
    button { background: #14532d; color: white; font-weight: 700; }
  </style>
</head>
<body>
  <main>
    <header><div>Inbox</div><div>Teeka Yatra</div></header>
    <ol>%s</ol>
    <form method="get" action="/sim/inbound">
      <input name="phone" placeholder="+91 caregiver phone" aria-label="Caregiver phone" />
      <input name="message" value="STOP" aria-label="Inbound message" />
      <button type="submit">Send inbound SMS</button>
    </form>
  </main>
</body>
</html>
""" % items
