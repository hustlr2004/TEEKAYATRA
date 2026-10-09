from datetime import date

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.database import Base, get_db
from app.main import app
from app.models import Role, User
from app.seed import seed_demo_data
from app.services.analytics import (
    AnalyticsFilters,
    anomaly_detection,
    cohort_curves,
    coverage_by_block,
    coverage_by_district,
    data_quality_by_block,
    defaulter_risk_scores,
    dropout_rates,
    manager_dashboard,
    parse_external_register_csv,
    refresh_materialized_views,
    simulated_external_register_csv,
    timeliness_by_block,
    timeliness_distribution,
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
    by_block = {row.block: row for row in rows}
    assert by_block["Kankarbagh"].children == 7
    assert by_block["Kankarbagh"].completed_doses == 18
    assert by_block["Phulwari"].children == 7
    assert by_block["Rajgir"].completed_doses == 30
    assert coverage_by_district(db, date.today(), AnalyticsFilters(district="Patna"))[0]["children"] == 14


def test_materialized_coverage_view_refreshes_from_sql(db: Session) -> None:
    refresh_materialized_views(db, date.today())

    rows = db.execute(text("SELECT block, completed_doses FROM analytics_coverage_mv ORDER BY block")).all()

    assert ("Kankarbagh", 18) in rows
    assert ("Phulwari", 25) in rows
    assert ("Rajgir", 30) in rows


def test_dropout_rates_include_penta_and_mr_pairs(db: Session) -> None:
    rows = dropout_rates(db)
    by_key = {(row.block, row.start_code, row.end_code): row for row in rows}

    assert by_key[("Kankarbagh", "PENTA_1", "PENTA_3")].start_count == 2
    assert by_key[("Kankarbagh", "PENTA_1", "PENTA_3")].end_count == 0
    assert by_key[("Kankarbagh", "PENTA_1", "PENTA_3")].dropout_pct == 100.0
    assert by_key[("Rajgir", "PENTA_1", "PENTA_3")].start_count == 4
    assert by_key[("Phulwari", "MR_1", "MR_2")].dropout_pct == 0.0


def test_timeliness_percentage_is_aggregate_only(db: Session) -> None:
    rows = timeliness_by_block(db)
    distribution = {row.block: row for row in timeliness_distribution(db)}

    assert len(rows) == 3
    by_block = {row.block: row for row in rows}
    assert by_block["Kankarbagh"].total_doses == 18
    assert by_block["Kankarbagh"].timely_doses == 4
    assert by_block["Kankarbagh"].timeliness_pct == 22.22
    assert distribution["Kankarbagh"].early == 2
    assert distribution["Kankarbagh"].late == 12


def test_zero_dose_children_count_is_aggregate(db: Session) -> None:
    rows = zero_dose_by_block(db)

    assert len(rows) == 3
    by_block = {row.block: row.zero_dose_children for row in rows}
    assert by_block == {"Rajgir": 0, "Kankarbagh": 3, "Phulwari": 0}


def test_cohort_curves_and_risk_scores_are_aggregated(db: Session) -> None:
    cohorts = {row.birth_month: row for row in cohort_curves(db)}
    risks = {row.block: row for row in defaulter_risk_scores(db, date.today())}

    assert cohorts["2024-01"].children == 1
    assert cohorts["2024-01"].zero_dose_children == 1
    assert cohorts["2024-03"].penta1_coverage_pct == 100.0
    assert risks["Kankarbagh"].children == 7
    assert 0 <= risks["Kankarbagh"].avg_risk_score <= 1
    assert "missed due visits" in risks["Kankarbagh"].explanation


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


def test_anomaly_detection_flags_implausible_asha_volume(db: Session) -> None:
    from datetime import datetime

    from app.models import Child, Consent, Dose, DoseSource, Sex, Village

    db.add(Village(id=99, block="Spike", district="Patna"))
    db.flush()
    asha = db.scalars(select(User).where(User.role == Role.asha)).first()
    caregiver = db.scalars(select(User).where(User.role == Role.caregiver)).first()
    db.add(Consent(guardian_id=caregiver.id, purpose="store_child", granted_at=datetime(2026, 1, 1)))
    for idx in range(30):
        child_id = 10_000 + idx
        db.add(Child(id=child_id, dob=date(2026, 1, 1), sex=Sex.female, village_id=99, guardian_id=caregiver.id, asha_id=asha.id))
        db.add(Dose(child_id=child_id, vaccine_code="BCG", given_on=date(2026, 1, 1), recorded_by=asha.id, source=DoseSource.app))
    db.commit()

    anomalies = anomaly_detection(db, AnalyticsFilters(block="Spike"))

    assert len(anomalies) == 1
    assert anomalies[0].dose_count == 30
    assert anomalies[0].severity == "high"


def test_manager_dashboard_combines_all_metrics(db: Session) -> None:
    dashboard = manager_dashboard(db, date.today(), simulated_external_register_csv())

    assert set(dashboard) == {
        "coverage_by_block",
        "coverage_by_district",
        "dropout_rates",
        "timeliness",
        "timeliness_distribution",
        "zero_dose",
        "cohort_curves",
        "defaulter_risk",
        "anomalies",
        "data_quality",
        "alerts",
        "pagination",
        "filters",
    }
    assert dashboard["coverage_by_block"]
    assert dashboard["defaulter_risk"]
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
        manager_response = client.get("/analytics/manager?block=Kankarbagh&page=1&page_size=2", headers={"Authorization": "Bearer %s" % create_access_token(manager)})
        caregiver_response = client.get("/analytics/manager", headers={"Authorization": "Bearer %s" % create_access_token(caregiver)})
    finally:
        app.dependency_overrides.clear()

    assert manager_response.status_code == 200
    assert caregiver_response.status_code == 403
    assert "name" not in str(manager_response.json())
    assert "phone" not in str(manager_response.json())
    assert manager_response.json()["filters"]["block"] == "Kankarbagh"
    assert manager_response.json()["pagination"]["page_size"] == 2
