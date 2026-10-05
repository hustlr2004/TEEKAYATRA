from datetime import date, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app import main as main_module
from app.main import app
from app.models import AuditLog, Child, Consent, Grievance, NotificationChannel, NotificationLog, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services.auth import create_access_token
from app.services.crypto import encrypt_phone
from app.services.gamification import load_rules
from app.services.responsible_design import run_retention_job


SENSITIVE_KEYS = {"name", "phone", "guardian_name", "child_name", "caregiver", "mobile"}


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
    seed_responsible_data(session)
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
    main_module._rate_limit_buckets.clear()
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.clear()
        main_module._rate_limit_buckets.clear()


def seed_responsible_data(db: Session) -> None:
    db.add_all(
        [
            Village(id=1, block="A", district="Patna"),
            Village(id=2, block="B", district="Nalanda"),
        ]
    )
    db.flush()
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian One", phone=encrypt_phone("+910000000001"), village_id=1, pw_hash="hash"),
            User(id=2, role=Role.caregiver, name="Guardian Two", phone=encrypt_phone("+910000000002"), village_id=2, pw_hash="hash"),
            User(id=3, role=Role.asha, name="ASHA One", phone=encrypt_phone("+910000000003"), village_id=1, pw_hash="hash"),
            User(id=4, role=Role.manager, name="Manager", phone=encrypt_phone("+910000000004"), village_id=None, pw_hash="hash"),
            User(id=5, role=Role.admin, name="Admin", phone=encrypt_phone("+910000000005"), village_id=None, pw_hash="hash"),
        ]
    )
    db.flush()
    db.add_all(
        [
            Consent(guardian_id=1, purpose="store_child", granted_at=date(2026, 1, 1)),
            Consent(guardian_id=2, purpose="store_child", granted_at=date(2026, 1, 1)),
            Child(id=1, dob=date(2025, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=3, opt_in_sms=True, opt_in_ivr=False, opt_in_app=True),
            Child(id=2, dob=date(2025, 1, 1), sex=Sex.male, village_id=2, guardian_id=2, asha_id=3, opt_in_sms=True, opt_in_ivr=False, opt_in_app=True),
        ]
    )


def auth_headers(db: Session, user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer %s" % create_access_token(db.get(User, user_id))}


def test_ethics_leaderboard_exposes_only_aggregates(client: TestClient, db: Session) -> None:
    response = client.get("/leaderboard/village", headers=auth_headers(db, 3))

    assert response.status_code == 200
    payload = response.json()
    assert payload
    assert not contains_sensitive_key(payload)
    assert "children_count" in payload[0]
    assert "points" in payload[0]


def test_ethics_points_rules_can_never_go_negative() -> None:
    negatives: list[tuple[str, int]] = []

    def walk(value: Any, path: str) -> None:
        if isinstance(value, dict):
            for key, nested in value.items():
                walk(nested, "%s.%s" % (path, key))
        elif isinstance(value, list):
            for index, nested in enumerate(value):
                walk(nested, "%s[%s]" % (path, index))
        elif isinstance(value, int) and "max_doses" not in path and value < 0:
            negatives.append((path, value))

    walk(load_rules(), "rules")

    assert negatives == []


def test_manager_sync_pull_is_aggregate_and_field_masked(client: TestClient, db: Session) -> None:
    response = client.get("/sync/pull", headers=auth_headers(db, 4))

    assert response.status_code == 200
    body = response.json()
    assert body["doses"] == []
    assert body["conflicts"] == []
    assert body["children"]
    assert not contains_sensitive_key(body)
    assert "children_count" in body["children"][0]


def test_caregiver_data_export_and_delete_flow(client: TestClient, db: Session) -> None:
    export_response = client.get("/me/data/export", headers=auth_headers(db, 1))
    delete_response = client.delete("/me/data", headers=auth_headers(db, 1))

    assert export_response.status_code == 200
    body = export_response.json()
    assert body["user"]["phone"] == "+910000000001"
    assert body["children"][0]["id"] == 1
    assert "doses" in body["children"][0]
    assert delete_response.status_code == 200
    assert delete_response.json()["deleted_child_ids"] == [1]
    assert db.get(Child, 1) is None
    withdrawn = db.scalars(select(Consent).where(Consent.guardian_id == 1)).all()
    assert all(consent.withdrawn_at is not None for consent in withdrawn)


def test_grievance_form_and_admin_review(client: TestClient, db: Session) -> None:
    filed = client.post(
        "/grievances",
        headers=auth_headers(db, 1),
        json={"child_id": 1, "category": "access", "message": "Please correct a visit record.", "contact_preference": "phone"},
    )
    blocked = client.post(
        "/grievances",
        headers=auth_headers(db, 4),
        json={"category": "access", "message": "manager should not file individual grievance"},
    )
    listed = client.get("/grievances", headers=auth_headers(db, 5))

    assert filed.status_code == 201
    assert filed.json()["guardian_id"] == 1
    assert blocked.status_code == 403
    assert listed.status_code == 200
    assert listed.json()[0]["category"] == "access"


def test_data_retention_job_removes_expired_low_value_records(db: Session) -> None:
    old_day = date(2024, 1, 1)
    db.add(AuditLog(actor_id=1, action="read", resource_type="child", resource_id="1", purpose="old", ts=datetime(2024, 1, 1)))
    db.add(
        NotificationLog(
            guardian_id=1,
            child_id=1,
            channel=NotificationChannel.sms,
            reminder_type="missed",
            vaccine_code="BCG",
            language="en",
            recipient_phone="encrypted",
            message="old",
            scheduled_for=old_day,
        )
    )
    db.add(Grievance(guardian_id=1, category="access", message="old", status="closed", created_at=datetime(2023, 1, 1)))
    db.commit()

    result = run_retention_job(db, date(2026, 10, 4), audit_days=365, notification_days=180, closed_grievance_days=365)

    assert result.audit_logs_deleted == 1
    assert result.notifications_deleted == 1
    assert result.closed_grievances_deleted == 1


def test_rate_limiting_blocks_excess_requests(client: TestClient, db: Session, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(main_module, "RATE_LIMIT_MAX_REQUESTS", 2)
    main_module._rate_limit_buckets.clear()

    first = client.get("/villages", headers=auth_headers(db, 1))
    second = client.get("/villages", headers=auth_headers(db, 1))
    third = client.get("/villages", headers=auth_headers(db, 1))

    assert first.status_code == 200
    assert second.status_code == 200
    assert third.status_code == 429


def contains_sensitive_key(value: Any) -> bool:
    if isinstance(value, dict):
        for key, nested in value.items():
            if key in SENSITIVE_KEYS:
                return True
            if contains_sensitive_key(nested):
                return True
    if isinstance(value, list):
        return any(contains_sensitive_key(item) for item in value)
    return False
