from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Consent, Dose, Role, Sex, User, Village
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
    seed_sync_data(session)
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


def seed_sync_data(db: Session) -> None:
    db.add(Village(id=1, block="A", district="Patna"))
    db.flush()
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian", phone=encrypt_phone("+910000020001"), village_id=1, pw_hash="hash"),
            User(id=2, role=Role.asha, name="ASHA", phone=encrypt_phone("+910000020002"), village_id=1, pw_hash="hash"),
        ]
    )
    db.flush()
    db.add(Consent(guardian_id=1, purpose="store_child", granted_at=datetime(2026, 1, 1)))
    db.add(
        Child(
            id=1,
            dob=date(2026, 1, 1),
            sex=Sex.female,
            village_id=1,
            guardian_id=1,
            asha_id=2,
            opt_in_sms=False,
            opt_in_ivr=False,
            opt_in_app=True,
            client_updated_at=datetime(2026, 1, 2, 10, 0),
        )
    )


def auth_headers(db: Session, user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer %s" % create_access_token(db.get(User, user_id))}


def test_duplicate_push_with_same_client_uuid_is_idempotent(client: TestClient, db: Session) -> None:
    payload = {
        "doses": [
            {
                "client_uuid": "dose-uuid-1",
                "child_id": 1,
                "vaccine_code": "BCG",
                "given_on": "2026-01-01",
                "source": "app",
                "client_updated_at": "2026-01-03T10:00:00",
            }
        ]
    }

    first = client.post("/sync/push", headers=auth_headers(db, 2), json=payload)
    second = client.post("/sync/push", headers=auth_headers(db, 2), json=payload)

    assert first.status_code == 200
    assert first.json()["accepted"] == ["dose-uuid-1"]
    assert second.status_code == 200
    assert second.json()["duplicates"] == ["dose-uuid-1"]
    assert len(db.scalars(select(Dose).where(Dose.client_uuid == "dose-uuid-1")).all()) == 1


def test_out_of_order_child_timestamp_is_flagged_and_does_not_overwrite(client: TestClient, db: Session) -> None:
    older = {
        "children": [
            {
                "id": 1,
                "client_updated_at": "2026-01-01T09:00:00",
                "opt_in_sms": True,
            }
        ]
    }
    newer = {
        "children": [
            {
                "id": 1,
                "client_updated_at": "2026-01-04T09:00:00",
                "opt_in_sms": True,
            }
        ]
    }

    older_response = client.post("/sync/push", headers=auth_headers(db, 2), json=older)
    child = db.get(Child, 1)
    assert older_response.status_code == 200
    assert older_response.json()["conflicts"][0]["type"] == "child_out_of_order"
    assert child.opt_in_sms is False
    assert child.conflict_flag is True

    newer_response = client.post("/sync/push", headers=auth_headers(db, 2), json=newer)
    assert newer_response.status_code == 200
    assert db.get(Child, 1).opt_in_sms is True


def test_conflicting_duplicate_vaccine_is_flagged_for_asha_review(client: TestClient, db: Session) -> None:
    first = {
        "doses": [
            {
                "client_uuid": "dose-uuid-a",
                "child_id": 1,
                "vaccine_code": "BCG",
                "given_on": "2026-01-01",
                "source": "app",
                "client_updated_at": "2026-01-03T10:00:00",
            }
        ]
    }
    conflict = {
        "doses": [
            {
                "client_uuid": "dose-uuid-b",
                "child_id": 1,
                "vaccine_code": "BCG",
                "given_on": "2026-01-02",
                "source": "paper",
                "client_updated_at": "2026-01-04T10:00:00",
            }
        ]
    }

    assert client.post("/sync/push", headers=auth_headers(db, 2), json=first).status_code == 200
    response = client.post("/sync/push", headers=auth_headers(db, 2), json=conflict)

    assert response.status_code == 200
    assert response.json()["conflicts"][0]["type"] == "dose_conflict"
    assert db.scalar(select(Dose).where(Dose.client_uuid == "dose-uuid-a")).conflict_flag is True


def test_pull_since_returns_synced_doses_and_conflicts(client: TestClient, db: Session) -> None:
    dose = Dose(
        child_id=1,
        vaccine_code="BCG",
        given_on=date(2026, 1, 1),
        recorded_by=2,
        source="app",
        synced_at=datetime.utcnow(),
        client_uuid="pull-uuid",
        client_updated_at=datetime.utcnow(),
        conflict_flag=True,
    )
    db.add(dose)
    db.commit()

    since = (datetime.utcnow() - timedelta(minutes=5)).isoformat()
    response = client.get("/sync/pull?since=%s" % since, headers=auth_headers(db, 2))

    assert response.status_code == 200
    body = response.json()
    assert body["doses"][0]["client_uuid"] == "pull-uuid"
    assert body["conflicts"][0]["type"] == "dose"
