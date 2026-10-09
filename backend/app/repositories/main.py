from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select

from ..models import Child, ConflictReviewItem, ConflictStatus, Consent, DeadLetterLog, Dose, Grievance, JobRun, NotificationLog, Role, SyncBatch, SyncChangeLog, User, VaccineSchedule, Village
from ..schemas.query import ListQuery
from .base import Repository


class MainRepository(Repository):
    def get_user(self, user_id: int) -> Optional[User]:
        return self.db.get(User, user_id)

    def users(self, options: ListQuery | None = None) -> List[User]:
        options = options or ListQuery(page_size=10_000)
        query = select(User)
        if options.role:
            query = query.where(User.role == Role(options.role))
        if options.q:
            query = query.where(User.name.ilike("%%%s%%" % options.q))
        sort_columns = {"id": User.id, "name": User.name, "role": User.role}
        sort_column = sort_columns.get(options.sort, User.id)
        query = query.order_by(sort_column.desc() if options.descending else sort_column.asc()).offset(options.offset).limit(options.limit)
        return list(self.db.scalars(query).all())

    def villages(self, options: ListQuery | None = None) -> List[Village]:
        options = options or ListQuery(page_size=10_000, sort="district")
        query = select(Village)
        if options.block:
            query = query.where(Village.block == options.block)
        if options.district:
            query = query.where(Village.district == options.district)
        if options.q:
            query = query.where((Village.block.ilike("%%%s%%" % options.q)) | (Village.district.ilike("%%%s%%" % options.q)))
        sort_columns = {"id": Village.id, "block": Village.block, "district": Village.district}
        sort_column = sort_columns.get(options.sort, Village.district)
        query = query.order_by(sort_column.desc() if options.descending else sort_column.asc(), Village.block.asc()).offset(options.offset).limit(options.limit)
        return list(self.db.scalars(query).all())

    def schedule_rows(self, options: ListQuery | None = None) -> List[VaccineSchedule]:
        options = options or ListQuery(page_size=10_000, sort="age_due_days")
        query = select(VaccineSchedule)
        if options.q:
            query = query.where((VaccineSchedule.vaccine_code.ilike("%%%s%%" % options.q)) | (VaccineSchedule.name.ilike("%%%s%%" % options.q)))
        sort_columns = {"id": VaccineSchedule.id, "age_due_days": VaccineSchedule.age_due_days, "vaccine_code": VaccineSchedule.vaccine_code, "name": VaccineSchedule.name}
        sort_column = sort_columns.get(options.sort, VaccineSchedule.age_due_days)
        query = query.order_by(sort_column.desc() if options.descending else sort_column.asc(), VaccineSchedule.vaccine_code.asc()).offset(options.offset).limit(options.limit)
        return list(self.db.scalars(query).all())

    def counts(self) -> dict[str, int]:
        return {
            "villages": self.db.scalar(select(func.count()).select_from(Village)) or 0,
            "users": self.db.scalar(select(func.count()).select_from(User)) or 0,
            "children": self.db.scalar(select(func.count()).select_from(Child).where(Child.deleted_at.is_(None))) or 0,
            "doses": self.db.scalar(select(func.count()).select_from(Dose)) or 0,
        }

    def get_consent(self, consent_id: int) -> Optional[Consent]:
        return self.db.get(Consent, consent_id)

    def active_consent(self, guardian_id: int, purpose: str) -> Optional[Consent]:
        return self.db.scalar(
            select(Consent).where(
                Consent.guardian_id == guardian_id,
                Consent.purpose == purpose,
                Consent.withdrawn_at.is_(None),
            )
        )

    def get_child(self, child_id: int) -> Optional[Child]:
        return self.db.scalar(select(Child).where(Child.id == child_id, Child.deleted_at.is_(None)))

    def children_for_actor(self, actor: User, options: ListQuery | None = None) -> List[Child]:
        options = options or ListQuery(page_size=10_000)
        query = select(Child).where(Child.deleted_at.is_(None))
        if actor.role.value == "caregiver":
            query = query.where(Child.guardian_id == actor.id)
        elif actor.role.value == "asha":
            query = query.where(Child.village_id == actor.village_id)
        if options.q:
            try:
                query = query.where(Child.id == int(options.q))
            except ValueError:
                query = query.where(Child.id == -1)
        sort_columns = {"id": Child.id, "dob": Child.dob, "village_id": Child.village_id, "guardian_id": Child.guardian_id}
        sort_column = sort_columns.get(options.sort, Child.id)
        query = query.order_by(sort_column.desc() if options.descending else sort_column.asc()).offset(options.offset).limit(options.limit)
        return list(self.db.scalars(query).all())

    def aggregated_children(self, options: ListQuery | None = None) -> List[dict[str, object]]:
        options = options or ListQuery(page_size=10_000, sort="district")
        query = (
            select(Village.id, Village.block, Village.district, func.count(Child.id).label("children_count"))
            .join(Child, (Child.village_id == Village.id) & (Child.deleted_at.is_(None)), isouter=True)
            .group_by(Village.id, Village.block, Village.district)
        )
        if options.block:
            query = query.where(Village.block == options.block)
        if options.district:
            query = query.where(Village.district == options.district)
        sort_columns = {"id": Village.id, "block": Village.block, "district": Village.district, "children_count": func.count(Child.id)}
        sort_column = sort_columns.get(options.sort, Village.district)
        rows = self.db.execute(query.order_by(sort_column.desc() if options.descending else sort_column.asc(), Village.block.asc()).offset(options.offset).limit(options.limit)).all()
        return [
            {
                "village_id": village_id,
                "block": block,
                "district": district,
                "children_count": count,
            }
            for village_id, block, district, count in rows
        ]

    def get_dose_by_uuid(self, client_uuid: str) -> Optional[Dose]:
        return self.db.scalar(select(Dose).where(Dose.client_uuid == client_uuid))

    def get_child_vaccine_dose(self, child_id: int, vaccine_code: str) -> Optional[Dose]:
        return self.db.scalar(select(Dose).where(Dose.child_id == child_id, Dose.vaccine_code == vaccine_code))

    def doses_for_children(self, child_ids: List[int], since: Optional[datetime]) -> List[Dose]:
        dose_query = select(Dose).where(Dose.child_id.in_(child_ids)).order_by(Dose.id)
        if since is not None:
            dose_query = dose_query.where(Dose.synced_at.is_not(None), Dose.synced_at >= since)
        return list(self.db.scalars(dose_query).all())

    def sync_batch(self, actor_id: int, idempotency_key: str) -> Optional[SyncBatch]:
        return self.db.scalar(select(SyncBatch).where(SyncBatch.actor_id == actor_id, SyncBatch.idempotency_key == idempotency_key))

    def changes_for_actor(self, actor: User, after_cursor: int) -> List[SyncChangeLog]:
        query = select(SyncChangeLog).where(SyncChangeLog.cursor > after_cursor).order_by(SyncChangeLog.cursor)
        if actor.role.value == "caregiver":
            child_ids = select(Child.id).where(Child.guardian_id == actor.id, Child.deleted_at.is_(None))
            query = query.where(SyncChangeLog.child_id.in_(child_ids))
        elif actor.role.value == "asha":
            query = query.where(SyncChangeLog.village_id == actor.village_id)
        return list(self.db.scalars(query).all())

    def conflict_review_queue(self, actor: User, options: ListQuery | None = None) -> List[ConflictReviewItem]:
        options = options or ListQuery(page_size=10_000, sort="created_at")
        query = select(ConflictReviewItem).where(ConflictReviewItem.status == ConflictStatus.open).order_by(ConflictReviewItem.created_at, ConflictReviewItem.id)
        if actor.role.value == "asha":
            query = query.where(ConflictReviewItem.village_id == actor.village_id)
        if options.status:
            query = query.where(ConflictReviewItem.status == ConflictStatus(options.status))
        query = query.offset(options.offset).limit(options.limit)
        return list(self.db.scalars(query).all())

    def notification_logs(self) -> List[NotificationLog]:
        return list(self.db.scalars(select(NotificationLog).order_by(NotificationLog.sent_at.desc(), NotificationLog.id.desc()).limit(30)).all())

    def grievances(self, options: ListQuery | None = None) -> List[Grievance]:
        options = options or ListQuery(page_size=10_000)
        query = select(Grievance)
        if options.status:
            query = query.where(Grievance.status == options.status)
        if options.q:
            query = query.where((Grievance.category.ilike("%%%s%%" % options.q)) | (Grievance.message.ilike("%%%s%%" % options.q)))
        sort_columns = {"id": Grievance.id, "status": Grievance.status, "created_at": Grievance.created_at, "category": Grievance.category}
        sort_column = sort_columns.get(options.sort, Grievance.id)
        query = query.order_by(sort_column.desc() if options.descending else sort_column.asc()).offset(options.offset).limit(options.limit)
        return list(self.db.scalars(query).all())

    def job_status(self) -> dict[str, object]:
        runs = self.db.scalars(select(JobRun).order_by(JobRun.started_at.desc(), JobRun.id.desc()).limit(25)).all()
        dead_letters = self.db.scalars(
            select(DeadLetterLog).order_by(DeadLetterLog.created_at.desc(), DeadLetterLog.id.desc()).limit(25)
        ).all()
        return {
            "jobs": [
                {
                    "id": row.id,
                    "job_name": row.job_name,
                    "status": row.status.value,
                    "attempts": row.attempts,
                    "started_at": row.started_at,
                    "finished_at": row.finished_at,
                    "error": row.error,
                }
                for row in runs
            ],
            "dead_letters": [
                {
                    "id": row.id,
                    "job_name": row.job_name,
                    "attempts": row.attempts,
                    "created_at": row.created_at,
                    "error": row.error,
                }
                for row in dead_letters
            ],
        }
