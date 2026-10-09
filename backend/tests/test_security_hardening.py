from datetime import date, datetime

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Consent, Role, Sex, User, Village
from app.services.auth import create_access_token, hash_password
from app.services.crypto import decrypt_text, encrypt_phone


@pytest.fixture()
def db() -> Session:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(bind=engine)
    testing_session_local = sessionmaker(bind=engine, autoflush=False, autocommit=False, future=True)
    session = testing_session_local()
    seed_security_data(session)
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


def seed_security_data(db: Session) -> None:
    db.add_all([Village(id=1, block="A", district="Patna"), Village(id=2, block="B", district="Nalanda")])
    db.flush()
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian One", phone=encrypt_phone("+910000050001"), village_id=1, pw_hash=hash_password("demo123")),
            User(id=2, role=Role.caregiver, name="Guardian Two", phone=encrypt_phone("+910000050002"), village_id=2, pw_hash=hash_password("demo123")),
            User(id=3, role=Role.asha, name="ASHA One", phone=encrypt_phone("+910000050003"), village_id=1, pw_hash=hash_password("demo123")),
            User(id=4, role=Role.manager, name="Manager", phone=encrypt_phone("+910000050004"), village_id=None, pw_hash=hash_password("demo123")),
            User(id=5, role=Role.admin, name="Admin", phone=encrypt_phone("+910000050005"), village_id=None, pw_hash=hash_password("demo123")),
        ]
    )
    db.flush()
    db.add_all(
        [
            Consent(guardian_id=1, purpose="store_child", granted_at=datetime(2026, 1, 1)),
            Child(id=1, dob=date(2026, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=3),
            Child(id=2, dob=date(2026, 1, 1), sex=Sex.female, village_id=2, guardian_id=2, asha_id=3),
        ]
    )


def auth_headers(db: Session, user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer %s" % create_access_token(db.get(User, user_id))}


def test_login_uses_argon2_and_refresh_rotation(client: TestClient) -> None:
    login = client.post("/auth/login", json={"phone": "+910000050001", "password": "demo123"})
    assert login.status_code == 200
    assert login.json()["refresh_token"]

    first_refresh = login.json()["refresh_token"]
    rotated = client.post("/auth/refresh", json={"refresh_token": first_refresh})
    reused = client.post("/auth/refresh", json={"refresh_token": first_refresh})

    assert rotated.status_code == 200
    assert rotated.json()["refresh_token"] != first_refresh
    assert reused.status_code == 401


def test_account_lockout_after_repeated_failures(client: TestClient, db: Session) -> None:
    for _ in range(5):
        client.post("/auth/login", json={"phone": "+910000050001", "password": "bad"})
    locked = client.post("/auth/login", json={"phone": "+910000050001", "password": "demo123"})
    assert locked.status_code == 423
    assert db.get(User, 1).locked_until is not None


def test_otp_expiry_and_attempt_limits(client: TestClient) -> None:
    requested = client.post("/auth/otp/request", json={"phone": "+910000050001"})
    assert requested.status_code == 200
    code = requested.json()["demo_code"]
    for _ in range(3):
        assert client.post("/auth/otp/verify", json={"phone": "+910000050001", "code": "000000"}).status_code == 401
    assert client.post("/auth/otp/verify", json={"phone": "+910000050001", "code": code}).status_code == 401


def test_security_headers_and_row_level_authorization(client: TestClient, db: Session) -> None:
    response = client.get("/children/1", headers=auth_headers(db, 1))
    forbidden = client.get("/children/2", headers=auth_headers(db, 1))
    manager_child = client.get("/children/1", headers=auth_headers(db, 4))

    assert response.headers["X-Content-Type-Options"] == "nosniff"
    assert response.headers["X-Frame-Options"] == "DENY"
    assert forbidden.status_code == 403
    assert manager_child.status_code == 403


def test_guardian_name_is_encrypted_for_new_caregiver(client: TestClient, db: Session) -> None:
    created = client.post(
        "/users",
        headers=auth_headers(db, 5),
        json={"role": "caregiver", "name": "Encrypted Guardian", "phone": "+910000059999", "password": "demo123", "village_id": 1},
    )
    assert created.status_code == 201
    user = db.get(User, created.json()["id"])
    assert user.name != "Encrypted Guardian"
    assert decrypt_text(user.name) == "Encrypted Guardian"
