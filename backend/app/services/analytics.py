from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import date
from io import StringIO
from typing import Dict, Iterable, List, Tuple

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import Child, Dose, StockLog, VaccineSchedule, Village


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
class ZeroDoseRow:
    block: str
    zero_dose_children: int


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


def coverage_by_block(db: Session, today: date) -> List[CoverageRow]:
    rows: List[CoverageRow] = []
    schedules = list(db.scalars(select(VaccineSchedule)).all())
    for village in _villages(db):
        children = _children_for_village(db, village.id)
        due = 0
        completed = 0
        for child in children:
            completed_codes = {dose.vaccine_code for dose in child.doses}
            for schedule in schedules:
                if (today - child.dob).days >= schedule.age_due_days:
                    due += 1
                    if schedule.vaccine_code in completed_codes:
                        completed += 1
        rows.append(
            CoverageRow(
                block=village.block,
                district=village.district,
                children=len(children),
                due_doses=due,
                completed_doses=completed,
                coverage_pct=_pct(completed, due),
            )
        )
    return rows


def dropout_rates(db: Session) -> List[DropoutRow]:
    rows: List[DropoutRow] = []
    for village in _villages(db):
        block_child_ids = [child.id for child in _children_for_village(db, village.id)]
        rows.append(_dropout_row(db, village.block, block_child_ids, "PENTA_1", "PENTA_3"))
        rows.append(_dropout_row(db, village.block, block_child_ids, "MR_1", "MR_2"))
    return rows


def timeliness_by_block(db: Session) -> List[TimelinessRow]:
    schedules = {row.vaccine_code: row for row in db.scalars(select(VaccineSchedule)).all()}
    rows: List[TimelinessRow] = []
    for village in _villages(db):
        total = 0
        timely = 0
        for child in _children_for_village(db, village.id):
            for dose in child.doses:
                schedule = schedules.get(dose.vaccine_code)
                if schedule is None:
                    continue
                total += 1
                due_on = child.dob.toordinal() + schedule.age_due_days
                due_until = due_on + schedule.window_days
                if due_on <= dose.given_on.toordinal() <= due_until:
                    timely += 1
        rows.append(TimelinessRow(village.block, total, timely, _pct(timely, total)))
    return rows


def zero_dose_by_block(db: Session) -> List[ZeroDoseRow]:
    return [
        ZeroDoseRow(block=village.block, zero_dose_children=len([child for child in _children_for_village(db, village.id) if not child.doses]))
        for village in _villages(db)
    ]


def data_quality_by_block(db: Session) -> List[DataQualityRow]:
    rows: List[DataQualityRow] = []
    for village in _villages(db):
        children = _children_for_village(db, village.id)
        child_scores = [_child_completeness(child) for child in children]
        doses = [dose for child in children for dose in child.doses]
        # The current schema stores sync time but not a separate data-entry timestamp.
        # Synced rows are the closest available proxy for same-day digital entry.
        same_day = [dose for dose in doses if dose.synced_at is not None]
        rows.append(
            DataQualityRow(
                block=village.block,
                data_completeness_score=round(sum(child_scores) / len(child_scores), 2) if child_scores else 100.0,
                same_day_entry_pct=_pct(len(same_day), len(doses)),
            )
        )
    return rows


def parse_external_register_csv(csv_text: str) -> Dict[Tuple[str, str], int]:
    parsed: Dict[Tuple[str, str], int] = {}
    reader = csv.DictReader(StringIO(csv_text))
    for row in reader:
        block = str(row["block"])
        vaccine_code = str(row["vaccine_code"])
        parsed[(block, vaccine_code)] = parsed.get((block, vaccine_code), 0) + int(row["count"])
    return parsed


def triangulation_alerts(db: Session, external_csv: str) -> List[MismatchAlert]:
    external = parse_external_register_csv(external_csv)
    recorded = _recorded_counts(db)
    stock = _stock_usage_counts(db)
    keys = sorted(set(recorded) | set(stock) | set(external))
    alerts: List[MismatchAlert] = []
    for block, vaccine_code in keys:
        recorded_count = recorded.get((block, vaccine_code), 0)
        stock_count = stock.get((block, vaccine_code), 0)
        external_count = external.get((block, vaccine_code), 0)
        spread = max(recorded_count, stock_count, external_count) - min(recorded_count, stock_count, external_count)
        if spread < 3:
            continue
        severity = "high" if spread >= 8 else "medium"
        alerts.append(
            MismatchAlert(
                block=block,
                vaccine_code=vaccine_code,
                recorded_doses=recorded_count,
                stock_usage=stock_count,
                external_register=external_count,
                severity=severity,
                message="Mismatch between recorded doses, stock usage, and external register",
                suggested_action="Hold extra outreach session in %s and reconcile paper/register entries" % block,
            )
        )
    return alerts


def manager_dashboard(db: Session, today: date, external_csv: str) -> dict[str, object]:
    return {
        "coverage_by_block": [row.__dict__ for row in coverage_by_block(db, today)],
        "dropout_rates": [row.__dict__ for row in dropout_rates(db)],
        "timeliness": [row.__dict__ for row in timeliness_by_block(db)],
        "zero_dose": [row.__dict__ for row in zero_dose_by_block(db)],
        "data_quality": [row.__dict__ for row in data_quality_by_block(db)],
        "alerts": [row.__dict__ for row in triangulation_alerts(db, external_csv)],
    }


def simulated_external_register_csv() -> str:
    return "\n".join(
        [
            "block,vaccine_code,count",
            "Kankarbagh,BCG,2",
            "Phulwari,BCG,14",
            "Rajgir,BCG,1",
            "Kankarbagh,PENTA_1,4",
            "Phulwari,PENTA_1,4",
        ]
    )


def _dropout_row(db: Session, block: str, child_ids: Iterable[int], start_code: str, end_code: str) -> DropoutRow:
    ids = list(child_ids)
    if not ids:
        return DropoutRow(block, start_code, end_code, 0, 0, 0.0)
    start = db.scalar(select(func.count()).select_from(Dose).where(Dose.child_id.in_(ids), Dose.vaccine_code == start_code)) or 0
    end = db.scalar(select(func.count()).select_from(Dose).where(Dose.child_id.in_(ids), Dose.vaccine_code == end_code)) or 0
    return DropoutRow(block, start_code, end_code, int(start), int(end), _pct(int(start) - int(end), int(start)))


def _recorded_counts(db: Session) -> Dict[Tuple[str, str], int]:
    rows = db.execute(
        select(Village.block, Dose.vaccine_code, func.count(Dose.id))
        .join(Child, Child.id == Dose.child_id)
        .join(Village, Village.id == Child.village_id)
        .group_by(Village.block, Dose.vaccine_code)
    ).all()
    return {(block, vaccine_code): int(count) for block, vaccine_code, count in rows}


def _stock_usage_counts(db: Session) -> Dict[Tuple[str, str], int]:
    rows = db.execute(
        select(Village.block, StockLog.vaccine_code, func.sum(StockLog.delta))
        .join(Village, Village.id == StockLog.village_id)
        .group_by(Village.block, StockLog.vaccine_code)
    ).all()
    return {(block, vaccine_code): abs(int(delta or 0)) for block, vaccine_code, delta in rows}


def _child_completeness(child: Child) -> float:
    fields = [child.dob, child.sex, child.village_id, child.guardian_id, child.asha_id]
    present = len([item for item in fields if item is not None])
    return round((present / len(fields)) * 100, 2)


def _children_for_village(db: Session, village_id: int) -> List[Child]:
    return list(db.scalars(select(Child).where(Child.village_id == village_id)).all())


def _villages(db: Session) -> List[Village]:
    return list(db.scalars(select(Village).order_by(Village.district, Village.block)).all())


def _pct(numerator: int, denominator: int) -> float:
    if denominator <= 0:
        return 0.0
    return round((numerator / denominator) * 100, 2)
