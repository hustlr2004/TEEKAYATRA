from datetime import date
from io import BytesIO

import pytest
from fastapi.testclient import TestClient
from pypdf import PdfReader
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Consent, Role, Sex, User, Village
from app.seed import seed_vaccine_schedule
from app.services.auth import create_access_token
from app.services.cards import vaccination_card_pdf
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
    seed_vaccine_schedule(session)
    seed_card_data(session)
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


def seed_card_data(db: Session) -> None:
    db.add_all([Village(id=1, block="A", district="Patna"), Village(id=2, block="B", district="Nalanda")])
    db.flush()
    db.add_all(
        [
            User(id=1, role=Role.caregiver, name="Guardian One", phone=encrypt_phone("+910000000001"), village_id=1, pw_hash="hash"),
            User(id=2, role=Role.caregiver, name="Guardian Two", phone=encrypt_phone("+910000000002"), village_id=2, pw_hash="hash"),
            User(id=3, role=Role.asha, name="ASHA One", phone=encrypt_phone("+910000000003"), village_id=1, pw_hash="hash"),
            User(id=4, role=Role.manager, name="Manager", phone=encrypt_phone("+910000000004"), village_id=None, pw_hash="hash"),
        ]
    )
    db.flush()
    db.add_all(
        [
            Consent(guardian_id=1, purpose="store_child", granted_at=date(2026, 1, 1)),
            Child(id=1, dob=date(2025, 1, 1), sex=Sex.female, village_id=1, guardian_id=1, asha_id=3, opt_in_sms=True, opt_in_ivr=False, opt_in_app=True),
            Child(id=2, dob=date(2025, 1, 1), sex=Sex.male, village_id=2, guardian_id=2, asha_id=3, opt_in_sms=True, opt_in_ivr=False, opt_in_app=True),
        ]
    )


def auth_headers(db: Session, user_id: int) -> dict[str, str]:
    return {"Authorization": "Bearer %s" % create_access_token(db.get(User, user_id))}


def test_child_card_pdf_contains_printable_sections(client: TestClient, db: Session) -> None:
    response = client.get("/children/1/card.pdf", headers=auth_headers(db, 1))

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert response.content.startswith(b"%PDF")

    text = extract_text(response.content)
    assert "Teeka Yatra Vaccination Card" in text
    assert "Child details" in text
    assert "Next visit box" in text
    assert "Helpline" in text
    assert "Side effects" in text
    assert "QR: child ID only" in text
    assert "Guardian One" not in text
    assert "+910000000001" not in text


def test_blank_card_template_pdf(client: TestClient, db: Session) -> None:
    response = client.get("/children/card-template.pdf", headers=auth_headers(db, 3))

    assert response.status_code == 200
    assert response.content.startswith(b"%PDF")
    text = extract_text(response.content)
    assert "________" in text
    assert "Birth" in text
    assert "Stamp" in text


def test_manager_cannot_print_child_level_card(client: TestClient, db: Session) -> None:
    child_response = client.get("/children/1/card.pdf", headers=auth_headers(db, 4))
    blank_response = client.get("/children/card-template.pdf", headers=auth_headers(db, 4))

    assert child_response.status_code == 403
    assert blank_response.status_code == 403


def test_qr_payload_contains_only_child_id(monkeypatch: pytest.MonkeyPatch, db: Session) -> None:
    payloads = []

    def fake_qr(payload: str):
        payloads.append(payload)
        from PIL import Image

        return Image.new("RGB", (16, 16), "white")

    monkeypatch.setattr("app.services.cards.qrcode.make", fake_qr)
    vaccination_card_pdf(db, db.get(Child, 1))
    vaccination_card_pdf(db, None)

    assert payloads == ["child:1", "blank-template"]


def extract_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)
