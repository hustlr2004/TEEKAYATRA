from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import Dict, List, Optional, Sequence, Tuple

from sqlalchemy import Float, case, cast, distinct, func, literal, select, text
from sqlalchemy.orm import Session

from ..models import Child, Dose, StockLog, User, VaccineSchedule, Village


@dataclass(frozen=True)
class AnalyticsFilters:
    block: Optional[str] = None
    district: Optional[str] = None
    start_date: Optional[date] = None
    end_date: Optional[date] = None
    page: int = 1
    page_size: int = 50


@dataclass(frozen=True)
class CoverageRow:
    block: str
    district: str
    children: int
    due_doses: int
    completed_doses: int
    coverage_pct: float


@dataclass(frozen=True)
class DropoutRow:
    block: str
    start_code: str
    end_code: str
    start_count: int
    end_count: int
    dropout_pct: float


@dataclass(frozen=True)
class TimelinessRow:
    block: str
    total_doses: int
    timely_doses: int
    timeliness_pct: float


@dataclass(frozen=True)
class TimelinessDistributionRow:
    block: str
    early: int
    on_time: int
    late: int
    total: int


@dataclass(frozen=True)
class ZeroDoseRow:
    block: str
    district: str
    zero_dose_children: int


@dataclass(frozen=True)
class CohortCurveRow:
    birth_month: str
    children: int
    zero_dose_children: int
    penta1_coverage_pct: float
    penta3_coverage_pct: float
    mr1_coverage_pct: float


@dataclass(frozen=True)
class RiskScoreRow:
    block: str
    district: str
    children: int
    high_risk_children: int
    avg_risk_score: float
    explanation: str


@dataclass(frozen=True)
class AnomalyRow:
    asha_id: int
    asha_name: str
    block: str
    entry_date: date
    dose_count: int
    expected_daily_volume: float
    severity: str
    reason: str


@dataclass(frozen=True)
class DataQualityRow:
    block: str
    data_completeness_score: float
    same_day_entry_pct: float


@dataclass(frozen=True)
class MismatchAlert:
    block: str
    vaccine_code: str
    recorded_doses: int
    stock_usage: int
    external_register: int
    severity: str
    message: str
    suggested_action: str


def coverage_by_block(db: Session, today: date, filters: Optional[AnalyticsFilters] = None) -> List[CoverageRow]:
    filters = filters or AnalyticsFilters()
    query = (
        select(Village.block, Village.district, func.count(distinct(Child.id)), func.count(), func.count(Dose.id))
        .select_from(Child)
        .join(Village, Village.id == Child.village_id)
        .join(VaccineSchedule, _age_days_expr(today) >= VaccineSchedule.age_due_days)
        .join(Dose, (Dose.child_id == Child.id) & (Dose.vaccine_code == VaccineSchedule.vaccine_code), isouter=True)
        .where(Child.deleted_at.is_(None))
        .group_by(Village.block, Village.district)
        .order_by(Village.district, Village.block)
    )
    query = _apply_geo_filters(query, filters)
    return [CoverageRow(str(block), str(district), int(children), int(due), int(done), _pct(int(done), int(due))) for block, district, children, due, done in _page(db.execute(query).all(), filters)]


def coverage_by_district(db: Session, today: date, filters: Optional[AnalyticsFilters] = None) -> List[dict[str, object]]:
    filters = filters or AnalyticsFilters()
    block_rows = coverage_by_block(db, today, AnalyticsFilters(district=filters.district, start_date=filters.start_date, end_date=filters.end_date, page=1, page_size=10_000))
    grouped: Dict[str, dict[str, object]] = {}
    for row in block_rows:
        item = grouped.setdefault(row.district, {"district": row.district, "children": 0, "due_doses": 0, "completed_doses": 0})
        item["children"] = int(item["children"]) + row.children
        item["due_doses"] = int(item["due_doses"]) + row.due_doses
        item["completed_doses"] = int(item["completed_doses"]) + row.completed_doses
    for item in grouped.values():
        item["coverage_pct"] = _pct(int(item["completed_doses"]), int(item["due_doses"]))
    return _page(list(grouped.values()), filters)


def dropout_rates(db: Session, filters: Optional[AnalyticsFilters] = None) -> List[DropoutRow]:
    filters = filters or AnalyticsFilters()
    rows: List[DropoutRow] = []
    for start_code, end_code in (("PENTA_1", "PENTA_3"), ("MR_1", "MR_2")):
        query = (
            select(
                Village.block,
                func.count(distinct(case((Dose.vaccine_code == start_code, Child.id)))).label("start_count"),
                func.count(distinct(case((Dose.vaccine_code == end_code, Child.id)))).label("end_count"),
            )
            .select_from(Child)
            .join(Village, Village.id == Child.village_id)
            .join(Dose, Dose.child_id == Child.id, isouter=True)
            .where(Child.deleted_at.is_(None))
            .group_by(Village.block)
            .order_by(Village.block)
        )
        query = _apply_geo_filters(_apply_dose_date_filters(query, filters), filters)
        for block, start, end in db.execute(query).all():
            rows.append(DropoutRow(str(block), start_code, end_code, int(start), int(end), _pct(max(int(start) - int(end), 0), int(start))))
    return _page(rows, filters)


def timeliness_by_block(db: Session, filters: Optional[AnalyticsFilters] = None) -> List[TimelinessRow]:
    filters = filters or AnalyticsFilters()
    day_age = _dose_age_days_expr()
    timely = func.sum(case(((day_age >= VaccineSchedule.age_due_days) & (day_age <= VaccineSchedule.age_due_days + VaccineSchedule.window_days), 1), else_=0))
    query = (
        select(Village.block, func.count(Dose.id), timely)
        .select_from(Dose)
        .join(Child, Child.id == Dose.child_id)
        .join(Village, Village.id == Child.village_id)
        .join(VaccineSchedule, VaccineSchedule.vaccine_code == Dose.vaccine_code)
        .where(Child.deleted_at.is_(None))
        .group_by(Village.block)
        .order_by(Village.block)
    )
    query = _apply_geo_filters(_apply_dose_date_filters(query, filters), filters)
    return [TimelinessRow(str(block), int(total), int(timely_count or 0), _pct(int(timely_count or 0), int(total))) for block, total, timely_count in _page(db.execute(query).all(), filters)]


def timeliness_distribution(db: Session, filters: Optional[AnalyticsFilters] = None) -> List[TimelinessDistributionRow]:
    filters = filters or AnalyticsFilters()
    day_age = _dose_age_days_expr()
    early = func.sum(case((day_age < VaccineSchedule.age_due_days, 1), else_=0))
    on_time = func.sum(case(((day_age >= VaccineSchedule.age_due_days) & (day_age <= VaccineSchedule.age_due_days + VaccineSchedule.window_days), 1), else_=0))
    late = func.sum(case((day_age > VaccineSchedule.age_due_days + VaccineSchedule.window_days, 1), else_=0))
    query = (
        select(Village.block, early, on_time, late, func.count(Dose.id))
        .select_from(Dose)
        .join(Child, Child.id == Dose.child_id)
        .join(Village, Village.id == Child.village_id)
        .join(VaccineSchedule, VaccineSchedule.vaccine_code == Dose.vaccine_code)
        .where(Child.deleted_at.is_(None))
        .group_by(Village.block)
        .order_by(Village.block)
    )
    query = _apply_geo_filters(_apply_dose_date_filters(query, filters), filters)
    return [TimelinessDistributionRow(str(block), int(early_count or 0), int(on_time_count or 0), int(late_count or 0), int(total)) for block, early_count, on_time_count, late_count, total in _page(db.execute(query).all(), filters)]


def zero_dose_by_block(db: Session, filters: Optional[AnalyticsFilters] = None) -> List[ZeroDoseRow]:
    filters = filters or AnalyticsFilters()
    query = (
        select(Village.block, Village.district, func.count(distinct(case((Dose.id.is_(None), Child.id)))))
        .select_from(Village)
        .join(Child, (Child.village_id == Village.id) & (Child.deleted_at.is_(None)), isouter=True)
        .join(Dose, Dose.child_id == Child.id, isouter=True)
        .group_by(Village.block, Village.district)
        .order_by(Village.district, Village.block)
    )
    query = _apply_geo_filters(query, filters)
    return [ZeroDoseRow(str(block), str(district), int(count)) for block, district, count in _page(db.execute(query).all(), filters)]


def cohort_curves(db: Session, filters: Optional[AnalyticsFilters] = None) -> List[CohortCurveRow]:
    filters = filters or AnalyticsFilters()
    birth_month = _month_expr(Child.dob).label("birth_month")
    query = (
        select(
            birth_month,
            func.count(distinct(Child.id)),
            func.count(distinct(case((Dose.id.is_(None), Child.id)))),
            func.count(distinct(case((Dose.vaccine_code == "PENTA_1", Child.id)))),
            func.count(distinct(case((Dose.vaccine_code == "PENTA_3", Child.id)))),
            func.count(distinct(case((Dose.vaccine_code == "MR_1", Child.id)))),
        )
        .select_from(Child)
        .join(Village, Village.id == Child.village_id)
        .join(Dose, Dose.child_id == Child.id, isouter=True)
        .where(Child.deleted_at.is_(None))
        .group_by(birth_month)
        .order_by(birth_month)
    )
    query = _apply_geo_filters(query, filters)
    if filters.start_date is not None:
        query = query.where(Child.dob >= filters.start_date)
    if filters.end_date is not None:
        query = query.where(Child.dob <= filters.end_date)
    return [CohortCurveRow(str(month), int(total), int(zero), _pct(int(p1), int(total)), _pct(int(p3), int(total)), _pct(int(mr), int(total))) for month, total, zero, p1, p3, mr in _page(db.execute(query).all(), filters)]


def data_quality_by_block(db: Session, filters: Optional[AnalyticsFilters] = None) -> List[DataQualityRow]:
    filters = filters or AnalyticsFilters()
    complete = case(((Child.dob.is_not(None)) & (Child.sex.is_not(None)) & (Child.village_id.is_not(None)) & (Child.guardian_id.is_not(None)) & (Child.asha_id.is_not(None)), 1), else_=0)
    query = (
        select(Village.block, func.avg(cast(complete, Float)) * 100, func.sum(case((Dose.synced_at.is_not(None), 1), else_=0)), func.count(Dose.id))
        .select_from(Child)
        .join(Village, Village.id == Child.village_id)
        .join(Dose, Dose.child_id == Child.id, isouter=True)
        .where(Child.deleted_at.is_(None))
        .group_by(Village.block)
        .order_by(Village.block)
    )
    query = _apply_geo_filters(_apply_dose_date_filters(query, filters), filters)
    return [DataQualityRow(str(block), round(float(score or 100), 2), _pct(int(same_day_count or 0), int(total or 0))) for block, score, same_day_count, total in _page(db.execute(query).all(), filters)]


def defaulter_risk_scores(db: Session, today: date, filters: Optional[AnalyticsFilters] = None) -> List[RiskScoreRow]:
    filters = filters or AnalyticsFilters()
    features = _risk_features(db, today, filters)
    scores = _logistic_risk_scores(features)
    by_block: Dict[Tuple[str, str], List[float]] = {}
    for feature, score in zip(features, scores):
        by_block.setdefault((str(feature["block"]), str(feature["district"])), []).append(score)
    explanation = "Risk is estimated from past late doses, missed due visits, and a village-distance proxy. Higher scores mean the child looks more likely to miss the next vaccination without follow-up."
    rows = [RiskScoreRow(block, district, len(values), len([value for value in values if value >= 0.6]), round(sum(values) / len(values), 3), explanation) for (block, district), values in sorted(by_block.items()) if values]
    return _page(rows, filters)


def anomaly_detection(db: Session, filters: Optional[AnalyticsFilters] = None) -> List[AnomalyRow]:
    filters = filters or AnalyticsFilters()
    query = (
        select(Dose.recorded_by, User.name, Village.block, Dose.given_on, func.count(Dose.id).label("dose_count"))
        .select_from(Dose)
        .join(User, User.id == Dose.recorded_by)
        .join(Child, Child.id == Dose.child_id)
        .join(Village, Village.id == Child.village_id)
        .where(Child.deleted_at.is_(None))
        .group_by(Dose.recorded_by, User.name, Village.block, Dose.given_on)
        .order_by(Dose.given_on, Dose.recorded_by)
    )
    query = _apply_geo_filters(_apply_dose_date_filters(query, filters), filters)
    rows = db.execute(query).all()
    if not rows:
        return []
    average = sum(int(row.dose_count) for row in rows) / len(rows)
    threshold = 20 if len(rows) < 5 else max(20, average * 3)
    anomalies = [AnomalyRow(int(row.recorded_by), str(row.name), str(row.block), row.given_on, int(row.dose_count), round(average, 2), "high" if int(row.dose_count) >= threshold * 1.5 else "medium", "Implausibly high same-day ASHA entry volume") for row in rows if int(row.dose_count) >= threshold]
    return _page(anomalies, filters)


def refresh_materialized_views(db: Session, today: date) -> None:
    dialect = db.get_bind().dialect.name
    if dialect == "postgresql":
        db.execute(text("DROP MATERIALIZED VIEW IF EXISTS analytics_coverage_mv"))
        db.execute(text("""
            CREATE MATERIALIZED VIEW analytics_coverage_mv AS
            SELECT villages.block AS block,
                   villages.district AS district,
                   COUNT(DISTINCT children.id) AS children,
                   COUNT(vaccine_schedules.id) AS due_doses,
                   COUNT(doses.id) AS completed_doses
            FROM children
            JOIN villages ON villages.id = children.village_id
            JOIN vaccine_schedules ON (:today::date - children.dob) >= vaccine_schedules.age_due_days
            LEFT JOIN doses ON doses.child_id = children.id AND doses.vaccine_code = vaccine_schedules.vaccine_code
            WHERE children.deleted_at IS NULL
            GROUP BY villages.block, villages.district
        """), {"today": today.isoformat()})
    else:
        db.execute(text("DROP TABLE IF EXISTS analytics_coverage_mv"))
        db.execute(text("""
        CREATE TABLE analytics_coverage_mv AS
        SELECT villages.block AS block,
               villages.district AS district,
               COUNT(DISTINCT children.id) AS children,
               COUNT(vaccine_schedules.id) AS due_doses,
               COUNT(doses.id) AS completed_doses
        FROM children
        JOIN villages ON villages.id = children.village_id
        JOIN vaccine_schedules ON julianday(:today) - julianday(children.dob) >= vaccine_schedules.age_due_days
        LEFT JOIN doses ON doses.child_id = children.id AND doses.vaccine_code = vaccine_schedules.vaccine_code
        WHERE children.deleted_at IS NULL
        GROUP BY villages.block, villages.district
        """), {"today": today.isoformat()})
    db.commit()


def parse_external_register_csv(csv_text: str) -> Dict[Tuple[str, str], int]:
    parsed: Dict[Tuple[str, str], int] = {}
    reader = csv.DictReader(StringIO(csv_text))
    for row in reader:
        block = str(row["block"])
        vaccine_code = str(row["vaccine_code"])
        parsed[(block, vaccine_code)] = parsed.get((block, vaccine_code), 0) + int(row["count"])
    return parsed


def triangulation_alerts(db: Session, external_csv: str, filters: Optional[AnalyticsFilters] = None) -> List[MismatchAlert]:
    filters = filters or AnalyticsFilters()
    external = parse_external_register_csv(external_csv)
    recorded = _recorded_counts(db, filters)
    stock = _stock_usage_counts(db, filters)
    keys = sorted(set(recorded) | set(stock) | set(external))
    alerts: List[MismatchAlert] = []
    for block, vaccine_code in keys:
        if filters.block and block != filters.block:
            continue
        recorded_count = recorded.get((block, vaccine_code), 0)
        stock_count = stock.get((block, vaccine_code), 0)
        external_count = external.get((block, vaccine_code), 0)
        spread = max(recorded_count, stock_count, external_count) - min(recorded_count, stock_count, external_count)
        if spread < 3:
            continue
        severity = "high" if spread >= 8 else "medium"
        alerts.append(MismatchAlert(block, vaccine_code, recorded_count, stock_count, external_count, severity, "Mismatch between recorded doses, stock usage, and external register", "Hold extra outreach session in %s and reconcile paper/register entries" % block))
    return _page(alerts, filters)


def manager_dashboard(db: Session, today: date, external_csv: str, filters: Optional[AnalyticsFilters] = None) -> dict[str, object]:
    filters = filters or AnalyticsFilters()
    return {
        "coverage_by_block": [row.__dict__ for row in coverage_by_block(db, today, filters)],
        "coverage_by_district": coverage_by_district(db, today, filters),
        "dropout_rates": [row.__dict__ for row in dropout_rates(db, filters)],
        "timeliness": [row.__dict__ for row in timeliness_by_block(db, filters)],
        "timeliness_distribution": [row.__dict__ for row in timeliness_distribution(db, filters)],
        "zero_dose": [row.__dict__ for row in zero_dose_by_block(db, filters)],
        "cohort_curves": [row.__dict__ for row in cohort_curves(db, filters)],
        "defaulter_risk": [row.__dict__ for row in defaulter_risk_scores(db, today, filters)],
        "anomalies": [row.__dict__ for row in anomaly_detection(db, filters)],
        "data_quality": [row.__dict__ for row in data_quality_by_block(db, filters)],
        "alerts": [row.__dict__ for row in triangulation_alerts(db, external_csv, filters)],
        "pagination": {"page": filters.page, "page_size": filters.page_size},
        "filters": {"block": filters.block, "district": filters.district, "start_date": str(filters.start_date) if filters.start_date else None, "end_date": str(filters.end_date) if filters.end_date else None},
    }


def simulated_external_register_csv() -> str:
    return "\n".join(["block,vaccine_code,count", "Kankarbagh,BCG,2", "Phulwari,BCG,14", "Rajgir,BCG,1", "Kankarbagh,PENTA_1,4", "Phulwari,PENTA_1,4"])


def _risk_features(db: Session, today: date, filters: AnalyticsFilters) -> List[dict[str, object]]:
    day_age = _dose_age_days_expr()
    late_count = func.sum(case((day_age > VaccineSchedule.age_due_days + VaccineSchedule.window_days, 1), else_=0))
    due_count = select(func.count(VaccineSchedule.id)).where(_age_days_expr(today) >= VaccineSchedule.age_due_days).correlate(Child).scalar_subquery()
    query = (
        select(Child.id, Village.block, Village.district, Village.id.label("village_id"), func.count(distinct(Dose.id)), late_count, due_count)
        .select_from(Child)
        .join(Village, Village.id == Child.village_id)
        .join(Dose, Dose.child_id == Child.id, isouter=True)
        .join(VaccineSchedule, VaccineSchedule.vaccine_code == Dose.vaccine_code, isouter=True)
        .where(Child.deleted_at.is_(None))
        .group_by(Child.id, Village.block, Village.district, Village.id)
        .order_by(Child.id)
    )
    query = _apply_geo_filters(query, filters)
    features = []
    for child_id, block, district, village_id, doses, late, due in db.execute(query).all():
        features.append({"child_id": child_id, "block": block, "district": district, "late": int(late or 0), "missed": max(int(due or 0) - int(doses or 0), 0), "distance": float(village_id or 0)})
    return features


def _logistic_risk_scores(features: Sequence[dict[str, object]]) -> List[float]:
    if not features:
        return []
    matrix = [[float(row["late"]), float(row["missed"]), float(row["distance"])] for row in features]
    labels = [1 if float(row["late"]) > 0 or float(row["missed"]) >= 2 else 0 for row in features]
    if len(set(labels)) < 2:
        return [min(0.95, 0.15 + 0.2 * values[0] + 0.08 * values[1]) for values in matrix]
    try:
        from sklearn.linear_model import LogisticRegression

        model = LogisticRegression(random_state=0)
        model.fit(matrix, labels)
        return [float(value) for value in model.predict_proba(matrix)[:, 1]]
    except Exception:
        return [min(0.95, 0.15 + 0.2 * values[0] + 0.08 * values[1]) for values in matrix]


def _recorded_counts(db: Session, filters: AnalyticsFilters) -> Dict[Tuple[str, str], int]:
    query = select(Village.block, Dose.vaccine_code, func.count(Dose.id)).join(Child, Child.id == Dose.child_id).join(Village, Village.id == Child.village_id).where(Child.deleted_at.is_(None)).group_by(Village.block, Dose.vaccine_code)
    query = _apply_geo_filters(_apply_dose_date_filters(query, filters), filters)
    return {(block, vaccine_code): int(count) for block, vaccine_code, count in db.execute(query).all()}


def _stock_usage_counts(db: Session, filters: AnalyticsFilters) -> Dict[Tuple[str, str], int]:
    query = select(Village.block, StockLog.vaccine_code, func.sum(StockLog.delta)).join(Village, Village.id == StockLog.village_id).group_by(Village.block, StockLog.vaccine_code)
    query = _apply_geo_filters(query, filters)
    if filters.start_date is not None:
        query = query.where(func.date(StockLog.ts) >= filters.start_date)
    if filters.end_date is not None:
        query = query.where(func.date(StockLog.ts) <= filters.end_date)
    return {(block, vaccine_code): abs(int(delta or 0)) for block, vaccine_code, delta in db.execute(query).all()}


def _age_days_expr(today: date):
    return cast(func.julianday(literal(today.isoformat())) - func.julianday(Child.dob), Float)


def _dose_age_days_expr():
    return cast(func.julianday(Dose.given_on) - func.julianday(Child.dob), Float)


def _month_expr(column):
    return func.strftime("%Y-%m", column)


def _apply_geo_filters(query, filters: AnalyticsFilters):
    if filters.block:
        query = query.where(Village.block == filters.block)
    if filters.district:
        query = query.where(Village.district == filters.district)
    return query


def _apply_dose_date_filters(query, filters: AnalyticsFilters):
    if filters.start_date is not None:
        query = query.where(Dose.given_on >= filters.start_date)
    if filters.end_date is not None:
        query = query.where(Dose.given_on <= filters.end_date)
    return query


def _page(items: Sequence, filters: AnalyticsFilters) -> List:
    page = max(filters.page, 1)
    page_size = min(max(filters.page_size, 1), 500)
    start = (page - 1) * page_size
    return list(items[start : start + page_size])


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)
