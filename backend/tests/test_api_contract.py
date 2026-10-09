from __future__ import annotations

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
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(bind=engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = session_factory()
    seed_vaccine_schedule(session)
    seed_contract_data(session)
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


def seed_contract_data(db: Session) -> None:
    db.add(Village(id=1, block="A", district="Patna"))
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian", phone=encrypt_phone("+910000010001"), village_id=1, pw_hash="hash"),
            User(id=2, role=Role.asha, name="ASHA", phone=encrypt_phone("+910000010002"), village_id=1, pw_hash="hash"),
        ]
    )
    db.add(Consent(guardian_id=1, purpose="store_child", granted_at=datetime(2026, 1, 1)))
    db.add(Child(id=1, dob=date(2026, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=2))


def auth_headers(db: Session, user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer %s" % create_access_token(db.get(User, user_id))}


def test_openapi_contract_includes_core_paths(client: TestClient) -> None:
    response = client.get("/openapi.json")

    assert response.status_code == 200
    paths = response.json()["paths"]
    for path in ["/health", "/children", "/children/{child_id}/schedule", "/sync/push", "/sync/pull", "/analytics/manager"]:
        assert path in paths
    assert "post" in paths["/sync/push"]
    assert "get" in paths["/children/{child_id}/schedule"]


def test_health_contract(client: TestClient) -> None:
    response = client.get("/health")

    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_error_contract_for_unauthorized_child_list(client: TestClient) -> None:
    response = client.get("/children")

    assert response.status_code == 401
    assert {"code", "message", "details", "request_id"}.issubset(response.json())


def test_schedule_contract_shape(client: TestClient, db: Session) -> None:
    response = client.get("/children/1/schedule", headers=auth_headers(db, 1))

    assert response.status_code == 200
    payload = response.json()
    assert {"child_id", "as_of", "schedule", "due", "overdue", "next_visit"}.issubset(payload)
    assert {"vaccine_code", "name", "due_on", "due_until", "status"}.issubset(payload["schedule"][0])


def test_sync_push_contract_requires_idempotency_key(client: TestClient, db: Session) -> None:
    response = client.post("/sync/push", headers=auth_headers(db, 2), json={"doses": []})

    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"
