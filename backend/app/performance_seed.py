from __future__ import annotations

import asyncio
from datetime import date, datetime, timedelta

from sqlalchemy import delete, select

from .database import SessionLocal, engine
from .models import Child, Consent, Dose, DoseSource, Role, Sex, User, Village
from .seed import seed_vaccine_schedule
from .services.auth import hash_password
from .services.crypto import encrypt_phone


CHILDREN_TARGET = 100_000
DOSES_TARGET = 1_000_000
DOSE_CODES = ["BCG", "BOPV_0", "HEPB_BIRTH", "BOPV_1", "PENTA_1", "FIPV_1", "RVV_1", "PCV_1", "BOPV_2", "PENTA_2"]


def seed_performance_data(sync_db, children_target: int = CHILDREN_TARGET, doses_target: int = DOSES_TARGET) -> None:
    _clear_perf_rows(sync_db)
    seed_vaccine_schedule(sync_db)
    password = hash_password("demo123")
    villages = [Village(block="Perf-%02d" % idx, district="Load") for idx in range(10)]
    sync_db.add_all(villages)
    sync_db.flush()
    ashas = [
        User(role=Role.asha, name="Perf ASHA %02d" % idx, phone=encrypt_phone("+918800%06d" % idx), village_id=villages[idx % len(villages)].id, pw_hash=password)
        for idx in range(50)
    ]
    manager = User(role=Role.manager, name="Perf Manager", phone=encrypt_phone("+918899999999"), pw_hash=password)
    guardians = [
        User(role=Role.caregiver, name="Perf Guardian %04d" % idx, phone=encrypt_phone("+918811%06d" % idx), village_id=villages[idx % len(villages)].id, pw_hash=password)
        for idx in range(2_000)
    ]
    sync_db.add_all(ashas + [manager] + guardians)
    sync_db.flush()
    now = datetime.utcnow()
    sync_db.bulk_save_objects([Consent(guardian_id=guardian.id, purpose="store_child", granted_at=now) for guardian in guardians])
    sync_db.flush()
    today = date.today()
    child_rows = []
    for idx in range(children_target):
        guardian = guardians[idx % len(guardians)]
        child_rows.append(
            Child(
                dob=today - timedelta(days=idx % 2200),
                sex=[Sex.female, Sex.male, Sex.other][idx % 3],
                village_id=guardian.village_id or villages[0].id,
                guardian_id=guardian.id,
                asha_id=ashas[idx % len(ashas)].id,
                opt_in_app=True,
            )
        )
    sync_db.bulk_save_objects(child_rows, return_defaults=True)
    sync_db.flush()
    dose_rows = []
    max_doses_per_child = min(len(DOSE_CODES), max(1, doses_target // max(children_target, 1)))
    for child in child_rows:
        for dose_index, code in enumerate(DOSE_CODES[:max_doses_per_child]):
            dose_rows.append(
                Dose(
                    child_id=child.id,
                    vaccine_code=code,
                    given_on=child.dob + timedelta(days=dose_index * 14),
                    recorded_by=child.asha_id,
                    source=DoseSource.app,
                    synced_at=now,
                    client_uuid="perf-%s-%s" % (child.id, code),
                )
            )
    sync_db.bulk_save_objects(dose_rows[:doses_target])
    sync_db.commit()


def _clear_perf_rows(sync_db) -> None:
    perf_villages = select(Village.id).where(Village.district == "Load")
    sync_db.execute(delete(Dose).where(Dose.client_uuid.like("perf-%")))
    sync_db.execute(delete(Child).where(Child.village_id.in_(perf_villages)))
    sync_db.execute(delete(Consent).where(Consent.guardian_id.in_(select(User.id).where(User.name.like("Perf %")))))
    sync_db.execute(delete(User).where(User.name.like("Perf %")))
    sync_db.execute(delete(Village).where(Village.district == "Load"))
    sync_db.commit()


async def async_main() -> None:
    async with engine.begin() as connection:
        await connection.run_sync(lambda sync_conn: None)
    async with SessionLocal() as db:
        await db.run_sync(seed_performance_data)


def main() -> None:
    asyncio.run(async_main())


if __name__ == "__main__":
    main()
