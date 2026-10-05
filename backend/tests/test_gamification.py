from datetime import date, datetime, timedelta
from typing import Optional

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditLog, Badge, Child, Dose, DoseSource, EntityType, Points, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services.auth import create_access_token
from app.services.gamification import (
    DoseRecordedEvent,
    award_data_quality_star,
    child_progress,
    on_dose_recorded,
    validate_new_dose,
    village_leaderboard,
)


@pytest.fixture()
def db() -> Session:
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    seed_vaccine_schedule(session)
    seed_people(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


def seed_people(db: Session) -> None:
    village = Village(id=1, block="Block A", district="Patna")
    other_village = Village(id=2, block="Block B", district="Nalanda")
    db.add_all([village, other_village])
    db.flush()
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian", phone="+910000010001", village_id=1, pw_hash="hash"),
            User(id=2, role=Role.asha, name="ASHA", phone="+910000010002", village_id=1, pw_hash="hash"),
            User(id=3, role=Role.manager, name="Manager", phone="+910000010003", village_id=None, pw_hash="hash"),
        ]
    )


def make_child(db: Session, dob: date) -> Child:
    child = Child(
        dob=dob,
        sex=Sex.female,
        village_id=1,
        guardian_id=1,
        asha_id=2,
        opt_in_sms=True,
        opt_in_ivr=False,
        opt_in_app=True,
    )
    db.add(child)
    db.commit()
    db.refresh(child)
    return child


def add_dose(
    db: Session,
    child: Child,
    vaccine_code: str,
    given_on: date,
    synced_at: Optional[datetime] = None,
) -> Dose:
    dose = Dose(
        child_id=child.id,
        vaccine_code=vaccine_code,
        given_on=given_on,
        recorded_by=2,
        source=DoseSource.app,
        synced_at=synced_at,
    )
    db.add(dose)
    db.commit()
    db.refresh(dose)
    return dose


def test_dose_recorded_awards_on_time_paper_referral_and_same_day_entry(db: Session) -> None:
    child = make_child(db, date(2026, 1, 1))
    dose = add_dose(db, child, "BCG", child.dob, datetime(2026, 1, 1, 9, 0))

    on_dose_recorded(db, DoseRecordedEvent(dose=dose, paper_card_updated=True, verified_referral=True))
    db.commit()

    caregiver_points = db.scalar(
        select(func.sum(Points.points)).where(Points.entity_type == EntityType.caregiver, Points.entity_id == child.guardian_id)
    )
    asha_points = db.scalar(
        select(func.sum(Points.points)).where(Points.entity_type == EntityType.asha, Points.entity_id == 2)
    )

    assert caregiver_points == 17
    assert asha_points == 5


def test_late_dose_gets_positive_catch_up_bonus_never_negative(db: Session) -> None:
    child = make_child(db, date(2025, 1, 1))
    dose = add_dose(db, child, "BCG", date(2025, 3, 1))

    on_dose_recorded(db, DoseRecordedEvent(dose=dose))
    db.commit()

    assert db.scalar(select(func.sum(Points.points)).where(Points.entity_type == EntityType.caregiver)) == 6


def test_whole_visit_set_completion_adds_bonus_and_level_progress(db: Session) -> None:
    child = make_child(db, date(2026, 1, 1))
    add_dose(db, child, "BCG", child.dob)
    add_dose(db, child, "BOPV_0", child.dob)
    final_dose = add_dose(db, child, "HEPB_BIRTH", child.dob)

    on_dose_recorded(db, DoseRecordedEvent(dose=final_dose))
    db.commit()

    progress = child_progress(db, child)
    assert progress.completed_milestones == 1
    assert progress.level == "Sapling"
    assert progress.points == 30
    assert village_leaderboard(db)[0].points >= 30


def test_streak_uses_14_day_grace_period(db: Session) -> None:
    child = make_child(db, date(2026, 1, 1))
    add_dose(db, child, "BCG", child.dob)
    add_dose(db, child, "BOPV_0", child.dob + timedelta(days=14))
    add_dose(db, child, "HEPB_BIRTH", child.dob + timedelta(days=30))

    assert child_progress(db, child).current_streak == 2


def test_badges_fully_immunised_by_1_booster_hero_and_village_champion(db: Session) -> None:
    child = make_child(db, date.today() - timedelta(days=300))
    codes = [
        "BCG",
        "BOPV_0",
        "HEPB_BIRTH",
        "BOPV_1",
        "PENTA_1",
        "FIPV_1",
        "RVV_1",
        "PCV_1",
        "BOPV_2",
        "PENTA_2",
        "RVV_2",
        "BOPV_3",
        "PENTA_3",
        "FIPV_2",
        "RVV_3",
        "PCV_2",
        "MR_1",
        "JE_1",
        "PCV_BOOSTER",
        "FIPV_3",
        "VITA_1",
        "MR_2",
        "DPT_BOOSTER_1",
        "BOPV_BOOSTER",
    ]
    last = None
    for index, code in enumerate(codes):
        last = add_dose(db, child, code, child.dob + timedelta(days=min(index, 250)))

    assert last is not None
    on_dose_recorded(db, DoseRecordedEvent(dose=last))
    db.commit()

    child_badges = set(db.scalars(select(Badge.name).where(Badge.entity_type == EntityType.child)).all())
    village_badges = set(db.scalars(select(Badge.name).where(Badge.entity_type == EntityType.village)).all())

    assert "Fully Immunised by 1" in child_badges
    assert "Booster Hero" in child_badges
    assert "Village Champion" in village_badges


def test_asha_and_manager_event_points(db: Session) -> None:
    child = make_child(db, date(2025, 1, 1))
    dose = add_dose(db, child, "BCG", date(2025, 3, 1), datetime(2025, 3, 1, 12, 0))
    on_dose_recorded(db, DoseRecordedEvent(dose=dose, defaulter_traced=True))
    award_data_quality_star(db, db.get(User, 3))
    db.commit()

    assert db.scalar(select(func.sum(Points.points)).where(Points.entity_type == EntityType.asha)) == 13
    assert db.scalar(select(func.sum(Points.points)).where(Points.entity_type == EntityType.manager)) == 10


def test_duplicate_dose_rejected_and_implausible_volume_flagged(db: Session) -> None:
    child = make_child(db, date(2026, 1, 1))
    add_dose(db, child, "BCG", child.dob)

    with pytest.raises(ValueError, match="Duplicate dose"):
        validate_new_dose(db, child.id, "BCG", 2, child.dob)

    for index in range(40):
        other_child = make_child(db, date(2026, 1, 1) - timedelta(days=index + 1))
        add_dose(db, other_child, "BCG", date(2026, 1, 1))

    flags = validate_new_dose(db, child.id, "PENTA_1", 2, date(2026, 1, 1))
    db.commit()

    assert flags == ["implausible_asha_daily_volume"]
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "flag")) == 1


def test_progress_and_village_leaderboard_endpoints_are_aggregated(db: Session) -> None:
    child = make_child(db, date(2026, 1, 1))
    dose = add_dose(db, child, "BCG", child.dob)
    on_dose_recorded(db, DoseRecordedEvent(dose=dose))
    db.commit()

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        token = create_access_token(db.get(User, 2))
        progress = client.get("/children/%s/progress" % child.id, headers={"Authorization": "Bearer %s" % token})
        leaderboard = client.get("/leaderboard/village", headers={"Authorization": "Bearer %s" % token})
    finally:
        app.dependency_overrides.clear()

    assert progress.status_code == 200
    assert progress.json()["child_id"] == child.id
    assert leaderboard.status_code == 200
    first_row = leaderboard.json()[0]
    assert "points" in first_row
    assert "children_count" in first_row
    assert "child" not in first_row
    assert "name" not in first_row
