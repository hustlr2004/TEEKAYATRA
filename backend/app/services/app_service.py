from __future__ import annotations

from dataclasses import asdict
from datetime import date, datetime
from typing import List, Optional

from fastapi import HTTPException, Response, status
from sqlalchemy.orm import Session

from ..core.security import create_access_token, hash_password, require_role, verify_password
from ..models import Child, Consent, Dose, DoseSource, Grievance, Role, User
from ..repositories.main import MainRepository
from ..schemas.api import ChildCreate, ConsentCreate, GrievanceCreate, LoginRequest, SyncPush, UserCreate
from .audit import audit_child_access
from .analytics import manager_dashboard, simulated_external_register_csv
from .cache import LEADERBOARD_CACHE_KEY, MANAGER_DASHBOARD_CACHE_KEY, get_json, invalidate_analytics_cache, set_json
from .cards import vaccination_card_pdf
from .crypto import decrypt_phone, encrypt_phone, masked_phone
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
        return {"access_token": create_access_token(user), "token_type": "bearer"}

    def login(self, payload: LoginRequest) -> dict[str, str]:
        user = None
        for candidate in self.repo.users():
            if decrypt_phone(candidate.phone) == payload.phone:
                user = candidate
                break
        if user is None or not verify_password(payload.password, user.pw_hash):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid phone or password")
        return {"access_token": create_access_token(user), "token_type": "bearer"}

    def create_user(self, payload: UserCreate, actor: User) -> dict[str, object]:
        require_role(actor, Role.admin)
        password_hash = payload.pw_hash or (hash_password(payload.password) if payload.password else "")
        if not password_hash:
            raise HTTPException(status_code=400, detail="Password is required")
        user = User(
            role=payload.role,
            name=payload.name,
            phone=encrypt_phone(payload.phone),
            village_id=payload.village_id,
            pw_hash=password_hash,
            preferred_language=payload.preferred_language,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user_public(user, include_phone=True)

    def list_users(self, actor: User) -> List[dict[str, object]]:
        require_role(actor, Role.admin)
        return [user_public(user, include_phone=True) for user in self.repo.users()]

    def list_villages(self) -> List[dict[str, object]]:
        return [{"id": village.id, "block": village.block, "district": village.district} for village in self.repo.villages()]

    def list_schedule(self) -> List[dict[str, object]]:
        return [
            {
                "vaccine_code": row.vaccine_code,
                "name": row.name,
                "age_due_days": row.age_due_days,
                "window_days": row.window_days,
                "endemic_only": row.endemic_only,
            }
            for row in self.repo.schedule_rows()
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

    def list_children(self, actor: User) -> List[dict[str, object]]:
        if actor.role == Role.manager:
            return self.repo.aggregated_children()
        children = self.repo.children_for_actor(actor)
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

    def list_grievances(self, actor: User) -> List[dict[str, object]]:
        require_role(actor, Role.admin)
        return [grievance_public(row) for row in self.repo.grievances()]

    def data_retention_job(self, actor: User) -> dict[str, int]:
        require_role(actor, Role.admin)
        return asdict(run_retention_job(self.db, date.today()))

    def village_leaderboard(self, actor: User) -> List[dict[str, object]]:
        if actor.role == Role.caregiver:
            raise HTTPException(status_code=403, detail="Caregivers cannot view leaderboards")
        cached = get_json(LEADERBOARD_CACHE_KEY)
        if isinstance(cached, list):
            return cached
        payload = [asdict(row) for row in gamified_village_leaderboard(self.db)]
        set_json(LEADERBOARD_CACHE_KEY, payload)
        return payload

    def manager_analytics(self, actor: User) -> dict[str, object]:
        require_role(actor, Role.manager, Role.admin)
        cached = get_json(MANAGER_DASHBOARD_CACHE_KEY)
        if isinstance(cached, dict):
            return cached
        payload = manager_dashboard(self.db, date.today(), simulated_external_register_csv())
        set_json(MANAGER_DASHBOARD_CACHE_KEY, payload)
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

    def sync_push(self, payload: SyncPush, actor: User) -> dict[str, object]:
        if actor.role not in {Role.asha, Role.admin}:
            raise HTTPException(status_code=403, detail="Only ASHAs and admins can push offline sync batches")
        accepted: List[str] = []
        duplicates: List[str] = []
        conflicts: List[dict[str, object]] = []
        for child_update in payload.children:
            child = self.accessible_child(child_update.id, actor)
            audit_child_access(self.db, actor.id, "write", child.id, "sync child update")
            if child.client_updated_at is None or child_update.client_updated_at >= child.client_updated_at:
                if child_update.opt_in_sms is not None:
                    child.opt_in_sms = child_update.opt_in_sms
                if child_update.opt_in_ivr is not None:
                    child.opt_in_ivr = child_update.opt_in_ivr
                if child_update.opt_in_app is not None:
                    child.opt_in_app = child_update.opt_in_app
                child.client_updated_at = child_update.client_updated_at
            else:
                child.conflict_flag = True
                conflicts.append({"type": "child_out_of_order", "child_id": child.id})
        for incoming in payload.doses:
            child = self.accessible_child(incoming.child_id, actor)
            if self.repo.get_dose_by_uuid(incoming.client_uuid) is not None:
                duplicates.append(incoming.client_uuid)
                continue
            existing_dose = self.repo.get_child_vaccine_dose(incoming.child_id, incoming.vaccine_code)
            if existing_dose is not None:
                existing_dose.conflict_flag = True
                conflicts.append(
                    {
                        "type": "dose_conflict",
                        "client_uuid": incoming.client_uuid,
                        "child_id": incoming.child_id,
                        "vaccine_code": incoming.vaccine_code,
                    }
                )
                continue
            dose = Dose(
                child_id=incoming.child_id,
                vaccine_code=incoming.vaccine_code,
                given_on=incoming.given_on,
                batch_no=incoming.batch_no,
                session_id=incoming.session_id,
                recorded_by=actor.id,
                source=DoseSource(incoming.source),
                synced_at=datetime.utcnow(),
                client_uuid=incoming.client_uuid,
                client_updated_at=incoming.client_updated_at,
            )
            self.db.add(dose)
            self.db.flush()
            publish_dose_recorded(self.db, dose, paper_card_updated=incoming.source == "paper")
            audit_child_access(self.db, actor.id, "write", child.id, "sync dose")
            accepted.append(incoming.client_uuid)
        self.db.commit()
        if accepted:
            invalidate_analytics_cache()
            try:
                process_outbox(self.db)
                self.db.commit()
            except Exception:
                self.db.commit()
        return {"accepted": accepted, "duplicates": duplicates, "conflicts": conflicts}

    def sync_pull(self, since: Optional[datetime], actor: User) -> dict[str, object]:
        if actor.role == Role.manager:
            return {"children": self.repo.aggregated_children(), "doses": [], "conflicts": []}
        children = self.repo.children_for_actor(actor)
        child_ids = [child.id for child in children]
        doses = self.repo.doses_for_children(child_ids, since)
        for child in children:
            audit_child_access(self.db, actor.id, "read", child.id, "sync pull")
        self.db.commit()
        return {
            "children": [child_public(child) | {"client_updated_at": child.client_updated_at, "conflict_flag": child.conflict_flag} for child in children],
            "doses": [dose_public(dose) for dose in doses],
            "conflicts": conflict_rows(children, doses),
            "server_time": datetime.utcnow().isoformat(),
        }

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
        "name": user.name,
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
