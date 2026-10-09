from __future__ import annotations

from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import NotificationLog, Points, Role, User, Village
from app.seed import seed_vaccine_schedule
from app.services.auth import create_access_token
from app.services.crypto import encrypt_phone
from app.services.notifications import schedule_reminders


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = session_factory()
    seed_vaccine_schedule(session)
    seed_journey_people(session)
    session.commit()
    try:
        yield session
    finally:
        session.close()


@pytest.fixture()
def client(db: Session) -> TestClient:
    def override_db():
        yield db

    app.dependency_overrides[get_db] = override_db
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()


def seed_journey_people(db: Session) -> None:
    db.add(Village(id=1, block="A", district="Patna"))
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Journey Guardian", phone=encrypt_phone("+910000030001"), village_id=1, pw_hash="hash", preferred_language="hi"),
            User(id=2, role=Role.asha, name="Journey ASHA", phone=encrypt_phone("+910000030002"), village_id=1, pw_hash="hash"),
            User(id=3, role=Role.manager, name="Journey Manager", phone=encrypt_phone("+910000030003"), village_id=None, pw_hash="hash"),
        ]
    )


def auth_headers(db: Session, user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer %s" % create_access_token(db.get(User, user_id))}


def sync_headers(db: Session, user_id: int, key: str) -> dict[str, str]:
    return {**auth_headers(db, user_id), "Idempotency-Key": key}


def test_register_consent_offline_sync_points_reminder_dashboard_journey(client: TestClient, db: Session) -> None:
    today = date.today()
    dob = today - timedelta(days=35)

    store_consent = client.post("/consents", headers=auth_headers(db, 1), json={"guardian_id": 1, "purpose": "store_child"})
    sms_consent = client.post("/consents", headers=auth_headers(db, 1), json={"guardian_id": 1, "purpose": "sms_reminders"})
    assert store_consent.status_code == 201
    assert sms_consent.status_code == 201

    child_response = client.post(
        "/children",
        headers=auth_headers(db, 1),
        json={
            "dob": dob.isoformat(),
            "sex": "female",
            "village_id": 1,
            "guardian_id": 1,
            "asha_id": 2,
            "opt_in_sms": True,
            "opt_in_ivr": False,
            "opt_in_app": True,
        },
    )
    assert child_response.status_code == 201
    child_id = child_response.json()["id"]

    sync_payload = {
        "doses": [
            {
                "client_uuid": "journey-bcg",
                "child_id": child_id,
                "vaccine_code": "BCG",
                "given_on": dob.isoformat(),
                "source": "app",
                "client_updated_at": datetime.utcnow().isoformat(),
            }
        ]
    }
    sync_response = client.post("/sync/push", headers=sync_headers(db, 2, "journey-sync"), json=sync_payload)
    assert sync_response.status_code == 200
    assert sync_response.json()["accepted"] == ["journey-bcg"]

    db.expire_all()
    caregiver_points = db.scalars(select(Points).where(Points.entity_id == 1)).all()
    assert any(point.points > 0 for point in caregiver_points)

    logs = schedule_reminders(db, today)
    db.commit()
    assert logs
    assert db.scalar(select(NotificationLog).where(NotificationLog.child_id == child_id)) is not None

    progress = client.get("/children/%s/progress" % child_id, headers=auth_headers(db, 1))
    dashboard = client.get("/analytics/manager", headers=auth_headers(db, 3))

    assert progress.status_code == 200
    assert progress.json()["points"] >= 0
    assert dashboard.status_code == 200
    assert {"coverage_by_block", "dropout_rates", "zero_dose"}.issubset(dashboard.json())
