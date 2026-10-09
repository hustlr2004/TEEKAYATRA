from datetime import date, datetime

import pytest
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base
from app.models import AuditLog, Child, Dose, DoseSource, EntityType, EventDelivery, EventStatus, Points, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services import event_bus
from app.services.event_bus import process_event, publish_dose_recorded


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
    session.add(Village(id=1, block="Block A", district="Patna"))
    session.flush()
    session.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian", phone="+910000030001", village_id=1, pw_hash="hash"),
            User(id=2, role=Role.asha, name="ASHA", phone="+910000030002", village_id=1, pw_hash="hash"),
        ]
    )
    session.flush()
    session.add(
        Child(
            id=1,
            dob=date(2026, 1, 1),
            sex=Sex.female,
            village_id=1,
            guardian_id=1,
            asha_id=2,
            opt_in_sms=True,
            opt_in_ivr=False,
            opt_in_app=True,
        )
    )
    session.commit()
    try:
        yield session
    finally:
        session.close()


def record_dose_and_event(db: Session) -> int:
    dose = Dose(
        child_id=1,
        vaccine_code="BCG",
        given_on=date(2026, 1, 1),
        recorded_by=2,
        source=DoseSource.app,
        synced_at=datetime(2026, 1, 1, 9, 0),
    )
    db.add(dose)
    db.flush()
    event = publish_dose_recorded(db, dose, paper_card_updated=True, verified_referral=True)
    db.commit()
    return event.id


def test_dose_recorded_event_triggers_all_subscribers_once_on_retry(db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    event_id = record_dose_and_event(db)
    original_reminder = event_bus._handle_reminder_rescheduling
    failures = {"count": 0}

    def flaky_reminder(session: Session, event) -> None:
        failures["count"] += 1
        if failures["count"] == 1:
            raise RuntimeError("temporary reminder failure")
        original_reminder(session, event)

    monkeypatch.setattr(event_bus, "_handle_reminder_rescheduling", flaky_reminder)
    event = db.get(event_bus.OutboxEvent, event_id)

    with pytest.raises(RuntimeError, match="temporary reminder failure"):
        process_event(db, event)
    db.commit()

    assert db.scalar(select(func.count()).select_from(Points).where(Points.entity_type == EntityType.caregiver)) == 1
    assert db.scalar(select(func.sum(Points.points)).where(Points.entity_type == EntityType.caregiver)) == 17

    process_event(db, db.get(event_bus.OutboxEvent, event_id))
    db.commit()

    deliveries = {
        delivery.subscriber: delivery
        for delivery in db.scalars(select(EventDelivery).where(EventDelivery.event_id == event_id)).all()
    }
    assert set(deliveries) == set(event_bus.dose_recorded_subscribers())
    assert all(delivery.status == EventStatus.processed for delivery in deliveries.values())
    assert deliveries["reminder_rescheduling"].attempts == 2
    assert all(delivery.attempts == 1 for name, delivery in deliveries.items() if name != "reminder_rescheduling")
    assert db.scalar(select(func.count()).select_from(Points).where(Points.entity_type == EntityType.caregiver)) == 1
    assert db.scalar(select(func.count()).select_from(Points).where(Points.entity_type == EntityType.asha)) == 1
    assert db.scalar(select(func.count()).select_from(AuditLog).where(AuditLog.action == "event")) == 4
