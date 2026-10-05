from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Consent, NotificationChannel, NotificationLog, NotificationOptOut, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services.crypto import encrypt_phone
from app.services.notifications import ivr_script, process_inbound_message, schedule_reminders


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
    seed_notification_data(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db: Session) -> TestClient:
    def override_db():
        try:
            yield db
        finally:
            pass

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def seed_notification_data(db: Session) -> None:
    db.add(Village(id=1, block="A", district="Patna"))
    db.flush()
    db.add_all(
        [
            User(
                id=1,
                role=Role.caregiver,
                name="Maya",
                phone=encrypt_phone("+910000000001"),
                village_id=1,
                pw_hash="hash",
                preferred_language="hi",
            ),
            User(id=2, role=Role.asha, name="ASHA", phone=encrypt_phone("+910000000002"), village_id=1, pw_hash="hash"),
        ]
    )
    db.flush()
    db.add_all(
        [
            Consent(guardian_id=1, purpose="sms_reminders", granted_at=date(2026, 1, 1)),
            Consent(guardian_id=1, purpose="ivr_reminders", granted_at=date(2026, 1, 1)),
            Child(id=1, dob=date(2025, 11, 27), sex=Sex.female, village_id=1, guardian_id=1, asha_id=2, opt_in_sms=True, opt_in_ivr=True, opt_in_app=True),
            Child(id=2, dob=date(2025, 11, 21), sex=Sex.male, village_id=1, guardian_id=1, asha_id=2, opt_in_sms=True, opt_in_ivr=False, opt_in_app=True),
            Child(id=3, dob=date(2025, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=2, opt_in_sms=True, opt_in_ivr=False, opt_in_app=True),
        ]
    )


def test_schedules_seven_day_one_day_and_missed_reminders(db: Session) -> None:
    sent = schedule_reminders(db, date(2026, 1, 1))

    logs = db.scalars(select(NotificationLog).order_by(NotificationLog.child_id, NotificationLog.channel)).all()
    by_child = {(log.child_id, log.reminder_type, log.channel.value) for log in logs}

    assert len(sent) == len(logs)
    assert (1, "seven_day", "sms") in by_child
    assert (1, "seven_day", "ivr") in by_child
    assert (2, "one_day", "sms") in by_child
    assert (3, "missed", "sms") in by_child
    assert all(log.language == "hi" for log in logs)
    assert any("Kripya" in log.message or "Catch-up" in log.message for log in logs)


def test_scheduler_is_idempotent_for_same_day(db: Session) -> None:
    first = schedule_reminders(db, date(2026, 1, 1))
    second = schedule_reminders(db, date(2026, 1, 1))

    assert len(first) > 0
    assert second == []
    assert db.scalar(select(func.count()).select_from(NotificationLog)) == len(first)


def test_ivr_script_is_text_to_speech_ready(db: Session) -> None:
    schedule_reminders(db, date(2026, 1, 1))
    log = db.scalar(select(NotificationLog).where(NotificationLog.channel == NotificationChannel.ivr))

    assert log is not None
    assert "Namaste" in log.message
    assert "repeat" in log.message.lower()


def test_stop_opt_out_blocks_future_sms(db: Session) -> None:
    assert process_inbound_message(db, "+910000000001", " STOP ") is True

    opt_out = db.scalar(select(NotificationOptOut).where(NotificationOptOut.guardian_id == 1))
    guardian_child = db.get(Child, 1)
    sent = schedule_reminders(db, date(2026, 1, 1))

    assert opt_out is not None
    assert opt_out.channel == NotificationChannel.sms
    assert guardian_child.opt_in_sms is False
    assert all(log.channel == NotificationChannel.ivr for log in sent)


def test_without_consent_no_messages_are_logged(db: Session) -> None:
    for consent in db.scalars(select(Consent)).all():
        db.delete(consent)
    db.commit()

    assert schedule_reminders(db, date(2026, 1, 1)) == []
    assert db.scalar(select(func.count()).select_from(NotificationLog)) == 0


def test_sim_page_renders_feature_phone_inbox(client: TestClient, db: Session) -> None:
    schedule_reminders(db, date(2026, 1, 1))

    response = client.get("/sim")

    assert response.status_code == 200
    assert "Inbox" in response.text
    assert "Teeka Yatra" in response.text
