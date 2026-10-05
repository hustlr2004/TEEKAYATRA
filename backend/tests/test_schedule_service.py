from datetime import date, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Dose, DoseSource, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services.auth import create_access_token
from app.services.schedule import due_doses, next_visit, overdue_doses, schedule_windows, timeliness


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
    endemic = Village(id=1, block="Block A", district="Endemic District")
    non_endemic = Village(id=2, block="Block B", district="Non Endemic District")
    db.add_all([endemic, non_endemic])
    db.flush()
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian", phone="+910000000001", village_id=1, pw_hash="hash"),
            User(id=2, role=Role.asha, name="ASHA", phone="+910000000002", village_id=1, pw_hash="hash"),
        ]
    )


def make_child(db: Session, age_days: int, village_id: int = 1) -> Child:
    child = Child(
        dob=date(2026, 1, 1) - timedelta(days=age_days),
        sex=Sex.female,
        village_id=village_id,
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


@pytest.mark.parametrize(
    ("age_days", "expected_codes"),
    [
        (0, {"BCG", "BOPV_0", "HEPB_BIRTH"}),
        (42, {"BOPV_1", "PENTA_1", "FIPV_1", "RVV_1", "PCV_1"}),
        (70, {"BOPV_2", "PENTA_2", "RVV_2"}),
        (98, {"BOPV_3", "PENTA_3", "FIPV_2", "RVV_3", "PCV_2"}),
        (274, {"MR_1", "JE_1", "PCV_BOOSTER", "FIPV_3", "VITA_1"}),
        (487, {"MR_2", "JE_2", "DPT_BOOSTER_1", "BOPV_BOOSTER", "VITA_2"}),
        (1826, {"DPT_BOOSTER_2"}),
        (3652, {"TD_10"}),
        (5844, {"TD_16"}),
    ],
)
def test_due_doses_cover_each_age_milestone(db: Session, age_days: int, expected_codes: set[str]) -> None:
    today = date(2026, 1, 1)
    child = make_child(db, age_days=age_days)
    due_codes = {window.vaccine_code for window in due_doses(child, today) if window.status == "due"}
    assert expected_codes.issubset(due_codes)


def test_overdue_doses_use_grace_windows_and_catch_up_status(db: Session) -> None:
    today = date(2026, 1, 1)
    child = make_child(db, age_days=336)

    overdue = overdue_doses(child, today)
    overdue_codes = {window.vaccine_code for window in overdue}

    assert "MR_1" in overdue_codes
    assert "VITA_1" in overdue_codes
    assert all(window.status == "catch_up" for window in overdue)


def test_dose_inside_grace_window_is_due_not_overdue(db: Session) -> None:
    today = date(2026, 1, 1)
    child = make_child(db, age_days=300)

    due_by_code = {window.vaccine_code: window for window in due_doses(child, today)}
    overdue_codes = {window.vaccine_code for window in overdue_doses(child, today)}

    assert due_by_code["MR_1"].status == "due"
    assert "MR_1" not in overdue_codes


def test_vitamin_a_recurs_every_six_months_up_to_five_years(db: Session) -> None:
    today = date(2026, 1, 1)
    child = make_child(db, age_days=1826)

    vitamin_a = [window for window in schedule_windows(child, today) if window.vaccine_code.startswith("VITA_")]

    assert [window.vaccine_code for window in vitamin_a] == ["VITA_%s" % index for index in range(1, 10)]
    gaps = [
        (vitamin_a[index].due_on - vitamin_a[index - 1].due_on).days
        for index in range(2, len(vitamin_a))
    ]
    assert set(gaps) == {183}
    assert vitamin_a[-1].due_on <= child.dob + timedelta(days=1826)


def test_endemic_only_je_hidden_for_non_endemic_districts(db: Session) -> None:
    today = date(2026, 1, 1)
    endemic_child = make_child(db, age_days=274, village_id=1)
    non_endemic_child = make_child(db, age_days=274, village_id=2)

    endemic_codes = {window.vaccine_code for window in schedule_windows(endemic_child, today)}
    non_endemic_codes = {window.vaccine_code for window in schedule_windows(non_endemic_child, today)}

    assert {"JE_1", "JE_2"}.issubset(endemic_codes)
    assert "JE_1" not in non_endemic_codes
    assert "JE_2" not in non_endemic_codes


def test_timeliness_classifies_on_time_grace_and_late_catch_up(db: Session) -> None:
    child = make_child(db, age_days=500)
    on_time = add_dose(db, child, "BCG", child.dob)
    grace = add_dose(db, child, "MR_1", child.dob + timedelta(days=300))
    late = add_dose(db, child, "MR_2", child.dob + timedelta(days=750))

    assert timeliness(on_time) == "on_time"
    assert timeliness(grace) == "grace"
    assert timeliness(late) == "late_catch_up"


def test_next_visit_returns_today_for_catch_up_child(db: Session) -> None:
    child = make_child(db, age_days=500)
    plan = next_visit(child)

    assert plan.status == "catch_up"
    assert plan.visit_on == date.today()
    assert any(window.status == "catch_up" for window in plan.vaccines)


def test_child_schedule_endpoint(db: Session) -> None:
    child = make_child(db, age_days=274)

    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    try:
        token = create_access_token(db.get(User, 2))
        response = TestClient(app).get("/children/%s/schedule" % child.id, headers={"Authorization": "Bearer %s" % token})
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    body = response.json()
    assert body["child_id"] == child.id
    assert "due" in body
    assert "overdue" in body
    assert "next_visit" in body


def add_dose(db: Session, child: Child, vaccine_code: str, given_on: date) -> Dose:
    dose = Dose(
        child_id=child.id,
        vaccine_code=vaccine_code,
        given_on=given_on,
        recorded_by=2,
        source=DoseSource.app,
    )
    db.add(dose)
    db.commit()
    db.refresh(dose)
    return dose
