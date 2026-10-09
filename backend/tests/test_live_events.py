from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Consent, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services.auth import create_access_token
from app.services.crypto import encrypt_phone


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
    seed_live_data(session)
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


def seed_live_data(db: Session) -> None:
    seed_vaccine_schedule(db)
    db.add_all([Village(id=1, block="A", district="Patna"), Village(id=2, block="B", district="Nalanda")])
    db.flush()
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian One", phone=encrypt_phone("+910000040001"), village_id=1, pw_hash="hash"),
            User(id=2, role=Role.asha, name="ASHA", phone=encrypt_phone("+910000040002"), village_id=1, pw_hash="hash"),
            User(id=3, role=Role.manager, name="Manager", phone=encrypt_phone("+910000040003"), village_id=None, pw_hash="hash"),
            User(id=4, role=Role.caregiver, name="Guardian Two", phone=encrypt_phone("+910000040004"), village_id=2, pw_hash="hash"),
        ]
    )
    db.flush()
    db.add_all(
        [
            Consent(guardian_id=1, purpose="store_child", granted_at=datetime(2026, 1, 1)),
            Consent(guardian_id=4, purpose="store_child", granted_at=datetime(2026, 1, 1)),
            Child(id=1, dob=date(2026, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=2),
            Child(id=2, dob=date(2026, 1, 1), sex=Sex.female, village_id=2, guardian_id=4, asha_id=2),
        ]
    )


def token(db: Session, user_id: int) -> str:
    return create_access_token(db.get(User, user_id))


def record_dose(client: TestClient, db: Session) -> None:
    response = client.post(
        "/sync/push",
        headers={"Authorization": "Bearer %s" % token(db, 2)},
        json={
            "doses": [
                {
                    "client_uuid": "live-dose-1",
                    "child_id": 1,
                    "vaccine_code": "BCG",
                    "given_on": "2026-01-01",
                    "source": "app",
                    "client_updated_at": "2026-01-03T10:00:00",
                }
            ]
        },
    )
    assert response.status_code == 200


def test_caregiver_sse_receives_tree_growth_for_own_child(client: TestClient, db: Session) -> None:
    record_dose(client, db)

    response = client.get("/events?once=true&token=%s" % token(db, 1))

    assert response.status_code == 200
    assert "event: caregiver.tree" in response.text
    assert '"type": "tree_grew"' in response.text
    assert '"child_id": 1' in response.text


def test_role_channels_mask_manager_payload_and_filter_other_caregivers(client: TestClient, db: Session) -> None:
    record_dose(client, db)

    other_caregiver = client.get("/events?once=true", headers={"Authorization": "Bearer %s" % token(db, 4)})
    manager = client.get("/events?once=true", headers={"Authorization": "Bearer %s" % token(db, 3)})

    assert other_caregiver.status_code == 200
    assert other_caregiver.text == ""
    assert manager.status_code == 200
    assert "event: manager.dashboard" in manager.text
    assert "dashboard_counters_updated" in manager.text
    assert "Guardian" not in manager.text
    assert "phone" not in manager.text


def test_sse_reconnect_uses_last_event_id(client: TestClient, db: Session) -> None:
    record_dose(client, db)
    first = client.get("/events?once=true", headers={"Authorization": "Bearer %s" % token(db, 3)})
    event_id = first.text.split("id: ", 1)[1].split("\n", 1)[0]

    replay = client.get(
        "/events?once=true",
        headers={
            "Authorization": "Bearer %s" % token(db, 3),
            "Last-Event-ID": event_id,
        },
    )

    assert replay.status_code == 200
    assert replay.text == ""
