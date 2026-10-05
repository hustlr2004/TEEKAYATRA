from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Child, Consent, Dose, Role, StockLog, User, VaccineSchedule, Village
from app.seed import all_vaccine_schedule_rows, seed_demo_data, seed_vaccine_schedule


def make_db():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    return testing_session_local()


def test_seed_vaccine_schedule_from_india_schedule() -> None:
    db = make_db()
    try:
        seed_vaccine_schedule(db)
        db.commit()
        expected_codes = {row[0] for row in all_vaccine_schedule_rows()}
        actual_codes = set(db.scalars(select(VaccineSchedule.vaccine_code)).all())
        assert expected_codes == actual_codes
        assert db.scalar(select(VaccineSchedule.endemic_only).where(VaccineSchedule.vaccine_code == "JE_1")) is True
        assert db.scalar(select(VaccineSchedule.age_due_days).where(VaccineSchedule.vaccine_code == "TD_16")) == 5844
    finally:
        db.close()


def test_demo_seed_has_requested_shape_and_varied_history() -> None:
    db = make_db()
    try:
        seed_demo_data(db)
        assert db.scalar(select(func.count()).select_from(Village)) == 3
        assert db.scalar(select(func.count()).select_from(User).where(User.role == Role.asha)) == 2
        assert db.scalar(select(func.count()).select_from(Child)) == 20
        assert db.scalar(select(func.count()).select_from(Consent)) > 0
        assert db.scalar(select(func.count()).select_from(StockLog)) == 3

        dose_counts = [len(child.doses) for child in db.scalars(select(Child).order_by(Child.id)).all()]
        assert min(dose_counts) == 0
        assert max(dose_counts) > 5
        assert db.scalar(select(func.count()).select_from(Dose)) > 20
    finally:
        db.close()
