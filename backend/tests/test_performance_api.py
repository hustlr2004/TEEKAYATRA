from __future__ import annotations

from datetime import date

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Child, Consent, Role, Sex, User, Village
from app.services.auth import create_access_token
from app.services.crypto import encrypt_phone


def test_list_endpoints_support_pagination_filtering_sorting_and_etags() -> None:
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool, future=True)
    Base.metadata.create_all(bind=engine)
    session = sessionmaker(bind=engine, future=True)()
    _seed(session)

    def override_db():
        yield session

    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        headers = {"Authorization": "Bearer %s" % create_access_token(session.get(User, 1)), "Accept-Encoding": "gzip"}
        response = client.get("/children?page=2&page_size=2&sort=dob&order=desc", headers=headers)
        assert response.status_code == 200
        assert [row["id"] for row in response.json()] == [3, 2]
        assert response.headers["ETag"]
        cached = client.get("/children?page=2&page_size=2&sort=dob&order=desc", headers={**headers, "If-None-Match": response.headers["ETag"]})
        assert cached.status_code == 304

        villages = client.get("/villages?district=Patna&sort=block&order=desc", headers=headers)
        assert [row["block"] for row in villages.json()] == ["B", "A"]
    finally:
        app.dependency_overrides.clear()
        session.close()


def _seed(db: Session) -> None:
    db.add_all([Village(id=1, block="A", district="Patna"), Village(id=2, block="B", district="Patna")])
    db.flush()
    db.add(User(id=1, role=Role.asha, name="ASHA", phone=encrypt_phone("+910000000001"), village_id=1, pw_hash="hash"))
    db.add(User(id=2, role=Role.manager, name="Manager", phone=encrypt_phone("+910000000002"), pw_hash="hash"))
    db.add(Consent(guardian_id=1, purpose="store_child", granted_at=date(2026, 1, 1)))
    for idx in range(1, 6):
        db.add(Child(id=idx, dob=date(2026, 1, idx), sex=Sex.female, village_id=1, guardian_id=1, asha_id=1))
    db.commit()
