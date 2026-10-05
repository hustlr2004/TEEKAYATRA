from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta
from typing import Any, Dict, List

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from ..models import AuditLog, Child, Consent, Dose, Grievance, NotificationLog, User
from .audit import audit_child_access
from .crypto import decrypt_phone, encrypt_phone


@dataclass(frozen=True)
class RetentionResult:
    audit_logs_deleted: int
    notifications_deleted: int
    closed_grievances_deleted: int


def caregiver_export(db: Session, caregiver: User) -> Dict[str, Any]:
    children = db.scalars(select(Child).where(Child.guardian_id == caregiver.id).order_by(Child.id)).all()
    for child in children:
        audit_child_access(db, caregiver.id, "read", child.id, "export my data")
    return {
        "user": {
            "id": caregiver.id,
            "role": caregiver.role.value,
            "name": caregiver.name,
            "phone": _safe_decrypt(caregiver.phone),
            "preferred_language": caregiver.preferred_language,
        },
        "children": [_export_child(child) for child in children],
        "consents": [
            {
                "purpose": consent.purpose,
                "granted_at": consent.granted_at.isoformat(),
                "withdrawn_at": consent.withdrawn_at.isoformat() if consent.withdrawn_at else None,
            }
            for consent in db.scalars(select(Consent).where(Consent.guardian_id == caregiver.id).order_by(Consent.id)).all()
        ],
        "grievances": [
            {
                "id": grievance.id,
                "category": grievance.category,
                "message": grievance.message,
                "status": grievance.status,
                "created_at": grievance.created_at.isoformat() if grievance.created_at else None,
            }
            for grievance in db.scalars(select(Grievance).where(Grievance.guardian_id == caregiver.id).order_by(Grievance.id)).all()
        ],
    }


def delete_caregiver_data(db: Session, caregiver: User) -> List[int]:
    children = db.scalars(select(Child).where(Child.guardian_id == caregiver.id)).all()
    child_ids = [child.id for child in children]
    for child in children:
        audit_child_access(db, caregiver.id, "delete", child.id, "delete my data")
        db.delete(child)
    for consent in db.scalars(select(Consent).where(Consent.guardian_id == caregiver.id)).all():
        consent.withdrawn_at = datetime.utcnow()
    caregiver.name = "Deleted caregiver"
    caregiver.phone = encrypt_phone("deleted-%s" % caregiver.id)
    return child_ids


def run_retention_job(
    db: Session,
    today: date,
    audit_days: int = 365,
    notification_days: int = 180,
    closed_grievance_days: int = 730,
) -> RetentionResult:
    audit_before = datetime.combine(today - timedelta(days=audit_days), datetime.min.time())
    notification_before = today - timedelta(days=notification_days)
    grievance_before = datetime.combine(today - timedelta(days=closed_grievance_days), datetime.min.time())

    audit_result = db.execute(delete(AuditLog).where(AuditLog.ts < audit_before))
    notification_result = db.execute(delete(NotificationLog).where(NotificationLog.scheduled_for < notification_before))
    grievance_result = db.execute(
        delete(Grievance).where(
            Grievance.status == "closed",
            Grievance.created_at < grievance_before,
        )
    )
    db.commit()
    return RetentionResult(
        audit_logs_deleted=audit_result.rowcount or 0,
        notifications_deleted=notification_result.rowcount or 0,
        closed_grievances_deleted=grievance_result.rowcount or 0,
    )


def _export_child(child: Child) -> Dict[str, Any]:
    return {
        "id": child.id,
        "dob": child.dob.isoformat(),
        "sex": child.sex.value,
        "village_id": child.village_id,
        "asha_id": child.asha_id,
        "opt_in_sms": child.opt_in_sms,
        "opt_in_ivr": child.opt_in_ivr,
        "opt_in_app": child.opt_in_app,
        "doses": [_export_dose(dose) for dose in child.doses],
    }


def _export_dose(dose: Dose) -> Dict[str, Any]:
    return {
        "vaccine_code": dose.vaccine_code,
        "given_on": dose.given_on.isoformat(),
        "batch_no": dose.batch_no,
        "source": dose.source.value,
    }


def _safe_decrypt(value: str) -> str:
    try:
        return decrypt_phone(value)
    except ValueError:
        return value
