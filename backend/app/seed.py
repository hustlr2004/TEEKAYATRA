from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta
from typing import Iterable, List

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .database import Base, SessionLocal, engine
from .models import (
    AuditLog,
    Badge,
    Child,
    Consent,
    Dose,
    DoseSource,
    EntityType,
    Grievance,
    ImmunizationSession,
    NotificationLog,
    NotificationOptOut,
    Points,
    Role,
    Sex,
    StockLog,
    User,
    VaccineSchedule,
    Village,
)
from .services.auth import hash_password
from .services.crypto import encrypt_phone


VACCINE_SCHEDULE_ROWS = [
    ("BCG", "BCG", 0, 0, False),
    ("BOPV_0", "bOPV-0", 0, 0, False),
    ("HEPB_BIRTH", "HepB birth dose", 0, 0, False),
    ("BOPV_1", "bOPV-1", 42, 0, False),
    ("PENTA_1", "Pentavalent-1", 42, 0, False),
    ("FIPV_1", "fIPV-1", 42, 0, False),
    ("RVV_1", "RVV-1", 42, 0, False),
    ("PCV_1", "PCV-1", 42, 0, False),
    ("BOPV_2", "bOPV-2", 70, 0, False),
    ("PENTA_2", "Pentavalent-2", 70, 0, False),
    ("RVV_2", "RVV-2", 70, 0, False),
    ("BOPV_3", "bOPV-3", 98, 0, False),
    ("PENTA_3", "Pentavalent-3", 98, 0, False),
    ("FIPV_2", "fIPV-2", 98, 0, False),
    ("RVV_3", "RVV-3", 98, 0, False),
    ("PCV_2", "PCV-2", 98, 0, False),
    ("MR_1", "MR-1", 274, 61, False),
    ("JE_1", "JE-1", 274, 61, True),
    ("PCV_BOOSTER", "PCV-Booster", 274, 61, False),
    ("FIPV_3", "fIPV-3", 274, 61, False),
    ("VITA_1", "Vitamin A 1st dose", 274, 61, False),
    ("MR_2", "MR-2", 487, 213, False),
    ("JE_2", "JE-2", 487, 213, True),
    ("DPT_BOOSTER_1", "DPT Booster-1", 487, 213, False),
    ("BOPV_BOOSTER", "bOPV Booster", 487, 213, False),
    ("VITA_2", "Vitamin A dose 2", 487, 213, False),
    ("DPT_BOOSTER_2", "DPT Booster-2", 1826, 365, False),
    ("TD_10", "Td", 3652, 0, False),
    ("TD_16", "Td", 5844, 0, False),
]


def vitamin_a_followups() -> List[tuple[str, str, int, int, bool]]:
    rows: List[tuple[str, str, int, int, bool]] = []
    for dose_number in range(3, 10):
        age_due_days = 487 + ((dose_number - 2) * 183)
        rows.append(
            (
                "VITA_%s" % dose_number,
                "Vitamin A dose %s" % dose_number,
                age_due_days,
                min(30, max(0, 1826 - age_due_days)),
                False,
            )
        )
    return rows


def all_vaccine_schedule_rows() -> List[tuple[str, str, int, int, bool]]:
    return VACCINE_SCHEDULE_ROWS + vitamin_a_followups()


def seed_vaccine_schedule(db: Session) -> None:
    existing = set(db.scalars(select(VaccineSchedule.vaccine_code)).all())
    for vaccine_code, name, age_due_days, window_days, endemic_only in all_vaccine_schedule_rows():
        if vaccine_code in existing:
            continue
        db.add(
            VaccineSchedule(
                vaccine_code=vaccine_code,
                name=name,
                age_due_days=age_due_days,
                window_days=window_days,
                endemic_only=endemic_only,
            )
        )


def reset_demo_data(db: Session) -> None:
    for model in [
        AuditLog,
        NotificationOptOut,
        NotificationLog,
        Grievance,
        Badge,
        Points,
        StockLog,
        Dose,
        ImmunizationSession,
        Consent,
        Child,
        User,
        Village,
        VaccineSchedule,
    ]:
        db.execute(delete(model))
    db.commit()


def seed_demo_data(db: Session, reset: bool = False) -> None:
    if reset:
        reset_demo_data(db)
    seed_vaccine_schedule(db)

    villages = [
        Village(block="Kankarbagh", district="Patna"),
        Village(block="Phulwari", district="Patna"),
        Village(block="Rajgir", district="Nalanda"),
    ]
    db.add_all(villages)
    db.flush()

    demo_password = hash_password("demo123")
    ashas = [
        User(role=Role.asha, name="Sunita Devi", phone=encrypt_phone("+919000000101"), village_id=villages[0].id, pw_hash=demo_password),
        User(role=Role.asha, name="Rekha Kumari", phone=encrypt_phone("+919000000102"), village_id=villages[1].id, pw_hash=demo_password),
    ]
    manager = User(role=Role.manager, name="Ravi Kumar", phone=encrypt_phone("+919000000201"), village_id=None, pw_hash=demo_password)
    db.add_all(ashas + [manager])
    db.flush()

    guardians: List[User] = []
    for index in range(20):
        guardian = User(
            role=Role.caregiver,
            name="Guardian %02d" % (index + 1),
            phone=encrypt_phone("+919100000%03d" % index),
            village_id=villages[index % len(villages)].id,
            pw_hash=demo_password,
            preferred_language=["en", "hi", "pa"][index % 3],
        )
        guardians.append(guardian)
    db.add_all(guardians)
    db.flush()

    children: List[Child] = []
    today = date.today()
    for index, guardian in enumerate(guardians):
        child = Child(
            dob=today - timedelta(days=30 + (index * 53)),
            sex=[Sex.female, Sex.male, Sex.other][index % 3],
            village_id=guardian.village_id or villages[0].id,
            guardian_id=guardian.id,
            asha_id=ashas[index % len(ashas)].id,
            opt_in_sms=index % 2 == 0,
            opt_in_ivr=index % 3 == 0,
            opt_in_app=True,
        )
        children.append(child)
    db.add_all(children)
    db.flush()

    sessions = [
        ImmunizationSession(village_id=village.id, date=today - timedelta(days=14 + idx))
        for idx, village in enumerate(villages)
    ]
    db.add_all(sessions)
    db.flush()

    seed_doses(db, children, ashas, sessions)
    seed_supporting_records(db, guardians, villages, sessions)
    db.commit()


def seed_doses(
    db: Session,
    children: Iterable[Child],
    ashas: List[User],
    sessions: List[ImmunizationSession],
) -> None:
    starter_codes = ["BCG", "BOPV_0", "HEPB_BIRTH", "BOPV_1", "PENTA_1", "FIPV_1", "RVV_1", "PCV_1"]
    for index, child in enumerate(children):
        history_size = index % (len(starter_codes) + 1)
        for dose_index, code in enumerate(starter_codes[:history_size]):
            db.add(
                Dose(
                    child_id=child.id,
                    vaccine_code=code,
                    given_on=child.dob + timedelta(days=dose_index * 12),
                    batch_no="BATCH-%02d-%02d" % (index, dose_index),
                    session_id=sessions[index % len(sessions)].id,
                    recorded_by=ashas[index % len(ashas)].id,
                    source=[DoseSource.app, DoseSource.paper, DoseSource.register][dose_index % 3],
                    synced_at=datetime.utcnow() if dose_index % 2 == 0 else None,
                )
            )


def seed_supporting_records(
    db: Session,
    guardians: List[User],
    villages: List[Village],
    sessions: List[ImmunizationSession],
) -> None:
    now = datetime.utcnow()
    for guardian in guardians[:8]:
        db.add(Consent(guardian_id=guardian.id, purpose="sms_reminders", granted_at=now))
        db.add(Consent(guardian_id=guardian.id, purpose="ivr_reminders", granted_at=now))
        db.add(Consent(guardian_id=guardian.id, purpose="care_coordination", granted_at=now))
    for village in villages:
        db.add(Points(entity_type=EntityType.village, entity_id=village.id, points=25, reason="catch-up completed"))
        db.add(Badge(entity_type=EntityType.village, entity_id=village.id, code="TEAM_PROGRESS", name="Team Progress"))
    for session in sessions:
        db.add(StockLog(vaccine_code="BCG", village_id=session.village_id, session_id=session.id, delta=-8, reason="session use"))
    db.add(AuditLog(actor_id=None, action="seed", resource_type="database", resource_id="demo", purpose="demo data"))


async def async_main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(Base.metadata.create_all)
    async with SessionLocal() as db:
        await db.run_sync(lambda sync_db: seed_demo_data(sync_db, reset=True))


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
