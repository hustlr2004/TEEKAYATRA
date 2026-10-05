from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import AuditLog, Child, Consent, Role, Sex, User, Village
from app.services.auth import create_access_token, hash_password
from app.services.crypto import decrypt_phone, encrypt_phone


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
    seed_access_data(session)
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


def seed_access_data(db: Session) -> None:
    db.add_all(
        [
            Village(id=1, block="A", district="Patna"),
            Village(id=2, block="B", district="Nalanda"),
        ]
    )
    db.flush()
    users = [
        User(id=1, role=Role.caregiver, name="Guardian One", phone=encrypt_phone("+910000000001"), village_id=1, pw_hash="hash"),
        User(id=2, role=Role.caregiver, name="Guardian Two", phone=encrypt_phone("+910000000002"), village_id=2, pw_hash="hash"),
        User(id=3, role=Role.asha, name="ASHA One", phone=encrypt_phone("+910000000003"), village_id=1, pw_hash="hash"),
        User(id=4, role=Role.asha, name="ASHA Two", phone=encrypt_phone("+910000000004"), village_id=2, pw_hash="hash"),
        User(id=5, role=Role.manager, name="Manager", phone=encrypt_phone("+910000000005"), village_id=None, pw_hash="hash"),
        User(id=6, role=Role.admin, name="Admin", phone=encrypt_phone("+910000000006"), village_id=None, pw_hash="hash"),
    ]
    db.add_all(users)
    db.flush()
    db.add_all(
        [
            Consent(guardian_id=1, purpose="store_child", granted_at=date(2026, 1, 1)),
            Consent(guardian_id=2, purpose="store_child", granted_at=date(2026, 1, 1)),
            Child(id=1, dob=date(2025, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=3, opt_in_sms=True, opt_in_ivr=False, opt_in_app=True),
            Child(id=2, dob=date(2025, 1, 1), sex=Sex.male, village_id=2, guardian_id=2, asha_id=4, opt_in_sms=False, opt_in_ivr=True, opt_in_app=True),
        ]
    )


def auth_headers(db: Session, user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer %s" % create_access_token(db.get(User, user_id))}


def test_phone_numbers_are_encrypted_at_rest(db: Session) -> None:
    user = db.get(User, 1)
    assert user.phone != "+910000000001"
    assert decrypt_phone(user.phone) == "+910000000001"


def test_caregiver_sees_only_own_children(client: TestClient, db: Session) -> None:
    own = client.get("/children/1", headers=auth_headers(db, 1))
    other = client.get("/children/2", headers=auth_headers(db, 1))
    listing = client.get("/children", headers=auth_headers(db, 1))

    assert own.status_code == 200
    assert other.status_code == 403
    assert [item["id"] for item in listing.json()] == [1]


def test_asha_sees_only_assigned_village(client: TestClient, db: Session) -> None:
    own_village = client.get("/children/1", headers=auth_headers(db, 3))
    other_village = client.get("/children/2", headers=auth_headers(db, 3))

    assert own_village.status_code == 200
    assert other_village.status_code == 403


def test_manager_gets_aggregated_data_only(client: TestClient, db: Session) -> None:
    child = client.get("/children/1", headers=auth_headers(db, 5))
    listing = client.get("/children", headers=auth_headers(db, 5))

    assert child.status_code == 403
    assert listing.status_code == 200
    row = listing.json()[0]
    assert "children_count" in row
    assert "guardian_id" not in row
    assert "phone" not in row
    assert "name" not in row


def test_only_admin_manages_users(client: TestClient, db: Session) -> None:
    blocked = client.post(
        "/users",
        headers=auth_headers(db, 5),
        json={"role": "asha", "name": "Blocked", "phone": "+919999999999", "village_id": 1, "pw_hash": "hash"},
    )
    created = client.post(
        "/users",
        headers=auth_headers(db, 6),
        json={"role": "asha", "name": "Allowed", "phone": "+919999999998", "village_id": 1, "pw_hash": "hash"},
    )

    assert blocked.status_code == 403
    assert created.status_code == 201
    saved = db.get(User, created.json()["id"])
    assert saved.phone != "+919999999998"
    assert created.json()["phone"] == "****9998"


def test_child_creation_requires_active_guardian_consent(client: TestClient, db: Session) -> None:
    no_consent_user = User(id=7, role=Role.caregiver, name="No Consent", phone=encrypt_phone("+910000000007"), village_id=1, pw_hash="hash")
    db.add(no_consent_user)
    db.commit()

    payload = {
        "dob": "2026-01-01",
        "sex": "female",
        "village_id": 1,
        "guardian_id": 7,
        "asha_id": 3,
        "opt_in_sms": True,
        "opt_in_ivr": False,
        "opt_in_app": True,
    }
    denied = client.post("/children", headers=auth_headers(db, 7), json=payload)
    assert denied.status_code == 400

    consent = client.post("/consents", headers=auth_headers(db, 7), json={"guardian_id": 7, "purpose": "store_child"})
    assert consent.status_code == 201
    created = client.post("/children", headers=auth_headers(db, 7), json=payload)
    assert created.status_code == 201

    withdrawn = client.post("/consents/%s/withdraw" % consent.json()["id"], headers=auth_headers(db, 7))
    assert withdrawn.status_code == 200
    second = dict(payload)
    second["dob"] = "2026-02-01"
    assert client.post("/children", headers=auth_headers(db, 7), json=second).status_code == 400


def test_delete_my_data_removes_caregiver_children(client: TestClient, db: Session) -> None:
    response = client.delete("/me/data", headers=auth_headers(db, 1))

    assert response.status_code == 200
    assert response.json()["deleted_child_ids"] == [1]
    assert db.get(Child, 1) is None


def test_login_accepts_phone_and_password(client: TestClient, db: Session) -> None:
    db.add(
        User(
            id=99,
            role=Role.caregiver,
            name="Demo Login User",
            phone=encrypt_phone("+910000000099"),
            village_id=1,
            pw_hash=hash_password("demo123"),
        )
    )
    db.commit()

    response = client.post("/auth/login", json={"phone": "+910000000099", "password": "demo123"})

    assert response.status_code == 200
    payload = response.json()
    assert payload["token_type"] == "bearer"
    assert payload["access_token"]


def test_child_reads_and_writes_are_audited(client: TestClient, db: Session) -> None:
    before = db.scalar(select(func.count()).select_from(AuditLog))
    client.get("/children/1", headers=auth_headers(db, 1))
    after_read = db.scalar(select(func.count()).select_from(AuditLog))
    assert after_read == before + 1

    payload = {
        "dob": "2026-01-01",
        "sex": "female",
        "village_id": 1,
        "guardian_id": 1,
        "asha_id": 3,
        "opt_in_sms": True,
        "opt_in_ivr": False,
        "opt_in_app": True,
    }
    client.post("/children", headers=auth_headers(db, 1), json=payload)
    assert db.scalar(select(func.count()).select_from(AuditLog)) == after_read + 1
