from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Role, User
from app.seed import seed_demo_data
from app.services.analytics import (
    coverage_by_block,
    data_quality_by_block,
    dropout_rates,
    manager_dashboard,
    parse_external_register_csv,
    simulated_external_register_csv,
    timeliness_by_block,
    triangulation_alerts,
    zero_dose_by_block,
)
from app.services.auth import create_access_token


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
    seed_demo_data(session)
    try:
        yield session
    finally:
        session.close()


def test_coverage_by_block_uses_seed_data(db: Session) -> None:
    rows = coverage_by_block(db, date.today())

    assert len(rows) == 3
    assert all(row.children > 0 for row in rows)
    assert all(0 <= row.coverage_pct <= 100 for row in rows)


def test_dropout_rates_include_penta_and_mr_pairs(db: Session) -> None:
    rows = dropout_rates(db)
    pairs = {(row.start_code, row.end_code) for row in rows}

    assert ("PENTA_1", "PENTA_3") in pairs
    assert ("MR_1", "MR_2") in pairs
    assert all(row.dropout_pct >= 0 for row in rows)


def test_timeliness_percentage_is_aggregate_only(db: Session) -> None:
    rows = timeliness_by_block(db)

    assert len(rows) == 3
    assert all(0 <= row.timeliness_pct <= 100 for row in rows)
    assert all(hasattr(row, "block") for row in rows)


def test_zero_dose_children_count_is_aggregate(db: Session) -> None:
    rows = zero_dose_by_block(db)

    assert len(rows) == 3
    assert sum(row.zero_dose_children for row in rows) > 0


def test_data_completeness_and_same_day_entry(db: Session) -> None:
    rows = data_quality_by_block(db)

    assert len(rows) == 3
    assert all(row.data_completeness_score == 100 for row in rows)
    assert any(row.same_day_entry_pct > 0 for row in rows)


def test_external_register_csv_parser() -> None:
    parsed = parse_external_register_csv("block,vaccine_code,count\nA,BCG,2\nA,BCG,3\n")

    assert parsed[("A", "BCG")] == 5


def test_triangulation_mismatch_alerts_include_suggested_action(db: Session) -> None:
    alerts = triangulation_alerts(db, simulated_external_register_csv())

    assert alerts
    assert all("Hold extra outreach session" in alert.suggested_action for alert in alerts)
    assert all(alert.severity in {"medium", "high"} for alert in alerts)


def test_manager_dashboard_combines_all_metrics(db: Session) -> None:
    dashboard = manager_dashboard(db, date.today(), simulated_external_register_csv())

    assert set(dashboard) == {"coverage_by_block", "dropout_rates", "timeliness", "zero_dose", "data_quality", "alerts"}
    assert dashboard["coverage_by_block"]
    assert dashboard["alerts"]


def test_manager_analytics_endpoint_is_manager_only(db: Session) -> None:
    def override_db():
        try:
            yield db
        finally:
            pass

    manager = db.scalars(select(User).where(User.role == Role.manager)).first()
    caregiver = db.scalars(select(User).where(User.role == Role.caregiver)).first()
    app.dependency_overrides[get_db] = override_db
    try:
        client = TestClient(app)
        manager_response = client.get("/analytics/manager", headers={"Authorization": "Bearer %s" % create_access_token(manager)})
        caregiver_response = client.get("/analytics/manager", headers={"Authorization": "Bearer %s" % create_access_token(caregiver)})
    finally:
        app.dependency_overrides.clear()

    assert manager_response.status_code == 200
    assert caregiver_response.status_code == 403
    assert "name" not in str(manager_response.json())
    assert "phone" not in str(manager_response.json())
