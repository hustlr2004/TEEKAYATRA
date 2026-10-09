from __future__ import annotations

from datetime import date, datetime, timedelta

from hypothesis import given, settings
from hypothesis import strategies as st
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import Child, Consent, Dose, DoseSource, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services.schedule import due_doses, overdue_doses, schedule_windows, timeliness


def make_db(age_days: int) -> tuple[Session, Child]:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    db = session_factory()
    seed_vaccine_schedule(db)
    db.add(Village(id=1, block="A", district="Patna"))
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian", phone="+910000000001", village_id=1, pw_hash="hash"),
            User(id=2, role=Role.asha, name="ASHA", phone="+910000000002", village_id=1, pw_hash="hash"),
        ]
    )
    db.add(Consent(guardian_id=1, purpose="store_child", granted_at=datetime(2026, 1, 1)))
    child = Child(
        id=1,
        dob=date(2026, 1, 1) - timedelta(days=age_days),
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
    return db, child


@settings(max_examples=40, deadline=None)
@given(age_days=st.integers(min_value=0, max_value=5844))
def test_due_doses_are_due_today_or_earlier(age_days: int) -> None:
    today = date(2026, 1, 1)
    db, child = make_db(age_days)
    try:
        due = due_doses(child, today)
        all_windows = {window.vaccine_code: window for window in schedule_windows(child, today)}

        assert all(window.due_on <= today for window in due)
        assert {window.vaccine_code for window in due}.issubset(all_windows)
    finally:
        db.close()


@settings(max_examples=40, deadline=None)
@given(age_days=st.integers(min_value=0, max_value=5844))
def test_overdue_doses_are_always_due_and_past_grace(age_days: int) -> None:
    today = date(2026, 1, 1)
    db, child = make_db(age_days)
    try:
        due_codes = {window.vaccine_code for window in due_doses(child, today)}
        overdue = overdue_doses(child, today)

        assert {window.vaccine_code for window in overdue}.issubset(due_codes)
        assert all(today > window.due_until for window in overdue)
        assert all(window.status == "catch_up" for window in overdue)
    finally:
        db.close()


@settings(max_examples=35, deadline=None)
@given(offset_days=st.integers(min_value=-30, max_value=120))
def test_timeliness_respects_due_date_and_grace_window(offset_days: int) -> None:
    db, child = make_db(400)
    try:
        given_on = child.dob + timedelta(days=274 + offset_days)
        dose = Dose(
            child_id=child.id,
            vaccine_code="MR_1",
            given_on=given_on,
            recorded_by=2,
            source=DoseSource.app,
        )
        db.add(dose)
        db.commit()
        db.refresh(dose)

        result = timeliness(dose)
        if offset_days < 0:
            assert result == "early"
        elif offset_days <= 0:
            assert result == "on_time"
        elif offset_days <= 61:
            assert result == "grace"
        else:
            assert result == "late_catch_up"
    finally:
        db.close()
