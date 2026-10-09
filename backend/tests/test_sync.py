from datetime import date, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Consent, Dose, SyncChangeLog, Role, Sex, User, Village
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


def sync_headers(db: Session, user_id: int, key: str) -> dict[str, str]:
    return {**auth_headers(db, user_id), "Idempotency-Key": key}


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

    first = client.post("/sync/push", headers=sync_headers(db, 2, "retry-1"), json=payload)
    second = client.post("/sync/push", headers=sync_headers(db, 2, "retry-1"), json=payload)

    assert first.status_code == 200
    assert first.json()["accepted"] == ["dose-uuid-1"]
    assert second.status_code == 200
    assert second.json() == first.json()
    assert len(db.scalars(select(Dose).where(Dose.client_uuid == "dose-uuid-1")).all()) == 1
    assert db.scalar(select(SyncChangeLog).where(SyncChangeLog.entity_type == "dose")).cursor == 1


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

    older_response = client.post("/sync/push", headers=sync_headers(db, 2, "child-old"), json=older)
    child = db.get(Child, 1)
    assert older_response.status_code == 200
    assert older_response.json()["results"][0]["status"] == "conflict"
    assert child.opt_in_sms is False
    assert child.conflict_flag is True

    newer_response = client.post("/sync/push", headers=sync_headers(db, 2, "child-new"), json=newer)
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

    assert client.post("/sync/push", headers=sync_headers(db, 2, "conflict-first"), json=first).status_code == 200
    response = client.post("/sync/push", headers=sync_headers(db, 2, "conflict-second"), json=conflict)

    assert response.status_code == 200
    assert response.json()["results"][0]["status"] == "conflict"
    assert db.scalar(select(Dose).where(Dose.client_uuid == "dose-uuid-a")).conflict_flag is True
    queue = client.get("/sync/conflicts", headers=auth_headers(db, 2))
    assert queue.status_code == 200
    assert queue.json()[0]["conflict_type"] == "dose_conflict"


def test_pull_cursor_ignores_clock_skew_and_returns_monotonic_changes(client: TestClient, db: Session) -> None:
    payload = {
        "doses": [
            {
                "client_uuid": "pull-uuid",
                "child_id": 1,
                "vaccine_code": "BCG",
                "given_on": "2026-01-01",
                "source": "app",
                "client_updated_at": "1970-01-01T00:00:00",
            }
        ]
    }
    assert client.post("/sync/push", headers=sync_headers(db, 2, "clock-skew"), json=payload).status_code == 200
    response = client.get("/sync/pull?cursor=0", headers=auth_headers(db, 2))

    assert response.status_code == 200
    body = response.json()
    assert body["doses"][0]["client_uuid"] == "pull-uuid"
    assert body["next_cursor"] >= 1
    replay = client.get("/sync/pull?cursor=%s" % body["next_cursor"], headers=auth_headers(db, 2))
    assert replay.json()["doses"] == []


def test_sync_push_requires_idempotency_key(client: TestClient, db: Session) -> None:
    response = client.post("/sync/push", headers=auth_headers(db, 2), json={"doses": []})
    assert response.status_code == 422


def test_duplicate_key_with_different_payload_is_rejected(client: TestClient, db: Session) -> None:
    first = {"doses": [{"client_uuid": "same-key-a", "child_id": 1, "vaccine_code": "BCG", "given_on": "2026-01-01", "source": "app", "client_updated_at": "2026-01-03T10:00:00"}]}
    second = {"doses": [{"client_uuid": "same-key-b", "child_id": 1, "vaccine_code": "PENTA_1", "given_on": "2026-02-12", "source": "app", "client_updated_at": "2026-01-03T10:00:00"}]}
    assert client.post("/sync/push", headers=sync_headers(db, 2, "same-key"), json=first).status_code == 200
    response = client.post("/sync/push", headers=sync_headers(db, 2, "same-key"), json=second)
    assert response.status_code == 409


def test_partial_failure_and_1000_item_batch(client: TestClient, db: Session) -> None:
    db.add_all(
        [
            Child(id=index, dob=date(2026, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=2)
            for index in range(2, 1002)
        ]
    )
    db.commit()
    doses = [
        {"client_uuid": "bulk-%s" % index, "child_id": index + 2, "vaccine_code": "BCG", "given_on": "2026-01-01", "source": "app", "client_updated_at": "2026-01-03T10:00:00"}
        for index in range(999)
    ]
    doses.append({"client_uuid": "bulk-bad", "child_id": 99999, "vaccine_code": "BCG", "given_on": "2026-01-01", "source": "app", "client_updated_at": "2026-01-03T10:00:00"})

    response = client.post("/sync/push", headers=sync_headers(db, 2, "bulk-1000"), json={"doses": doses})

    assert response.status_code == 200
    body = response.json()
    assert len(body["results"]) == 1000
    assert len(body["accepted"]) == 999
    assert body["rejected"][0]["reason"] == "Child not found"
