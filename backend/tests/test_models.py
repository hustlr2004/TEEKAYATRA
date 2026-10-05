from datetime import date

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Child, Dose, DoseSource, Role, Sex, User, VaccineSchedule, Village


def make_session() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return testing_session_local()


def test_requested_tables_exist() -> None:
    db = make_session()
    try:
        table_names = set(inspect(db.bind).get_table_names())
    finally:
        db.close()

    assert {
        "users",
        "villages",
        "children",
        "consents",
        "vaccine_schedules",
        "doses",
        "sessions",
        "stock_logs",
        "points",
        "badges",
        "audit_logs",
        "notification_logs",
        "notification_opt_outs",
        "grievances",
    }.issubset(table_names)


def test_model_relationships_and_enums_round_trip() -> None:
    db = make_session()
    try:
        village = Village(block="Kankarbagh", district="Patna")
        db.add(village)
        db.flush()
        guardian = User(role=Role.caregiver, name="Maya", phone="+919999990001", village_id=village.id, pw_hash="hash")
        asha = User(role=Role.asha, name="Sunita", phone="+919999990002", village_id=village.id, pw_hash="hash")
        db.add_all([guardian, asha])
        db.flush()
        child = Child(
            dob=date(2025, 1, 1),
            sex=Sex.female,
            village_id=village.id,
            guardian_id=guardian.id,
            asha_id=asha.id,
            opt_in_sms=True,
            opt_in_ivr=False,
            opt_in_app=True,
        )
        db.add(child)
        db.flush()
        db.add(
            Dose(
                child_id=child.id,
                vaccine_code="BCG",
                given_on=date(2025, 1, 1),
                recorded_by=asha.id,
                source=DoseSource.app,
            )
        )
        db.commit()

        saved = db.get(Child, child.id)
        assert saved is not None
        assert saved.guardian.role == Role.caregiver
        assert saved.asha.role == Role.asha
        assert saved.doses[0].source == DoseSource.app
    finally:
        db.close()


def test_vaccine_schedule_model_keeps_schedule_as_data() -> None:
    db = make_session()
    try:
        db.add(VaccineSchedule(vaccine_code="JE_1", name="JE-1", age_due_days=274, window_days=61, endemic_only=True))
        db.commit()
        row = db.query(VaccineSchedule).filter_by(vaccine_code="JE_1").one()
        assert row.endemic_only is True
        assert row.age_due_days == 274
    finally:
        db.close()
