from __future__ import annotations

from datetime import datetime
from typing import List, Optional

from sqlalchemy import func, select

from ..models import Child, Consent, DeadLetterLog, Dose, Grievance, JobRun, NotificationLog, User, VaccineSchedule, Village
from .base import Repository


class MainRepository(Repository):
    def get_user(self, user_id: int) -> Optional[User]:
        return self.db.get(User, user_id)

    def users(self) -> List[User]:
        return list(self.db.scalars(select(User).order_by(User.id)).all())

    def villages(self) -> List[Village]:
        return list(self.db.scalars(select(Village).order_by(Village.district, Village.block)).all())

    def schedule_rows(self) -> List[VaccineSchedule]:
        return list(self.db.scalars(select(VaccineSchedule).order_by(VaccineSchedule.age_due_days, VaccineSchedule.vaccine_code)).all())

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

    def children_for_actor(self, actor: User) -> List[Child]:
        query = select(Child).where(Child.deleted_at.is_(None)).order_by(Child.id)
        if actor.role.value == "caregiver":
            query = query.where(Child.guardian_id == actor.id)
        elif actor.role.value == "asha":
            query = query.where(Child.village_id == actor.village_id)
        return list(self.db.scalars(query).all())

    def aggregated_children(self) -> List[dict[str, object]]:
        rows = self.db.execute(
            select(Village.id, Village.block, Village.district, func.count(Child.id))
            .join(Child, (Child.village_id == Village.id) & (Child.deleted_at.is_(None)), isouter=True)
            .group_by(Village.id, Village.block, Village.district)
            .order_by(Village.district, Village.block)
        ).all()
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

    def notification_logs(self) -> List[NotificationLog]:
        return list(self.db.scalars(select(NotificationLog).order_by(NotificationLog.sent_at.desc(), NotificationLog.id.desc()).limit(30)).all())

    def grievances(self) -> List[Grievance]:
        return list(self.db.scalars(select(Grievance).order_by(Grievance.id)).all())

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
