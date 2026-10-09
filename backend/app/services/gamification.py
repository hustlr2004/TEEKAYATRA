from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Dict, List

import yaml
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..models import AuditLog, Badge, Child, Dose, EntityType, ImmunizationSession, Points, Role, User, VaccineSchedule, Village
from .schedule import timeliness


RULES_PATH = Path(__file__).resolve().parents[1] / "gamification_rules.yaml"


@dataclass(frozen=True)
class DoseRecordedEvent:
    dose: Dose
    paper_card_updated: bool = False
    verified_referral: bool = False
    defaulter_traced: bool = False


@dataclass(frozen=True)
class Progress:
    child_id: int
    caregiver_id: int
    points: int
    level: str
    completed_milestones: int
    current_streak: int
    badges: List[str]


@dataclass(frozen=True)
class VillageLeaderboardRow:
    village_id: int
    block: str
    district: str
    points: int
    children_count: int
    badges: int


def load_rules() -> Dict[str, Any]:
    with RULES_PATH.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle)


def validate_new_dose(db: Session, child_id: int, vaccine_code: str, recorded_by: int, given_on: date) -> List[str]:
    duplicate = db.scalar(select(Dose.id).where(Dose.child_id == child_id, Dose.vaccine_code == vaccine_code))
    if duplicate is not None:
        raise ValueError("Duplicate dose for child and vaccine_code")

    rules = load_rules()
    max_daily = int(rules["anti_gaming"]["max_doses_per_asha_per_day"])
    count = db.scalar(
        select(func.count())
        .select_from(Dose)
        .where(Dose.recorded_by == recorded_by, Dose.given_on == given_on)
    ) or 0
    if count >= max_daily:
        db.add(
            AuditLog(
                actor_id=recorded_by,
                action="flag",
                resource_type="dose",
                resource_id="%s:%s" % (child_id, vaccine_code),
                purpose="anti-gaming implausible volume",
                details='{"reason":"implausible_asha_daily_volume"}',
            )
        )
        return ["implausible_asha_daily_volume"]
    return []


def on_dose_recorded(db: Session, event: DoseRecordedEvent) -> List[Points]:
    rules = load_rules()
    dose = event.dose
    child = dose.child
    awards: List[Points] = []

    caregiver_points = _caregiver_points(db, child, dose, event, rules)
    if caregiver_points > 0:
        awards.append(_add_points(db, EntityType.caregiver, child.guardian_id, caregiver_points, "dose_recorded"))

    asha_points = _asha_points(dose, event, rules)
    if asha_points > 0:
        awards.append(_add_points(db, EntityType.asha, dose.recorded_by, asha_points, "asha_event"))

    village_bonus = _whole_visit_set_bonus(db, child, dose, rules)
    if village_bonus > 0:
        awards.append(_add_points(db, EntityType.village, child.village_id, village_bonus, "whole_visit_set_complete"))

    _award_badges(db, child, rules)
    return awards


def award_session_on_time(db: Session, session: ImmunizationSession) -> Points:
    rules = load_rules()
    points = int(rules["asha"]["session_on_time"])
    asha_ids = set(db.scalars(select(Child.asha_id).where(Child.village_id == session.village_id)).all())
    # Attribute a session-level award to the village when multiple ASHAs support the same site.
    award = _add_points(db, EntityType.village, session.village_id, points * max(1, len(asha_ids)), "session_on_time")
    return award


def award_data_quality_star(db: Session, manager: User) -> Points:
    if manager.role != Role.manager:
        raise ValueError("Data Quality Star can only be awarded to a manager")
    rules = load_rules()
    config = rules["manager"]["data_quality_star"]
    return _add_points(db, EntityType.manager, manager.id, int(config["points"]), str(config["reason"]))


def child_progress(db: Session, child: Child) -> Progress:
    points = db.scalar(
        select(func.coalesce(func.sum(Points.points), 0)).where(
            Points.entity_type == EntityType.caregiver,
            Points.entity_id == child.guardian_id,
        )
    ) or 0
    completed = completed_milestones(db, child)
    badges = list(
        db.scalars(
            select(Badge.name).where(
                Badge.entity_type == EntityType.child,
                Badge.entity_id == child.id,
            )
        ).all()
    )
    return Progress(
        child_id=child.id,
        caregiver_id=child.guardian_id,
        points=int(points),
        level=_level_for(completed, load_rules()),
        completed_milestones=completed,
        current_streak=current_streak(child),
        badges=badges,
    )


def village_leaderboard(db: Session) -> List[VillageLeaderboardRow]:
    villages = db.scalars(select(Village).order_by(Village.district, Village.block)).all()
    village_points = dict(
        db.execute(
            select(Points.entity_id, func.coalesce(func.sum(Points.points), 0))
            .where(Points.entity_type == EntityType.village)
            .group_by(Points.entity_id)
        ).all()
    )
    caregiver_points = dict(
        db.execute(
            select(Child.village_id, func.coalesce(func.sum(Points.points), 0))
            .join(Points, Points.entity_id == Child.guardian_id)
            .where(Points.entity_type == EntityType.caregiver)
            .group_by(Child.village_id)
        ).all()
    )
    children_counts = dict(
        db.execute(select(Child.village_id, func.count(Child.id)).group_by(Child.village_id)).all()
    )
    badge_counts = dict(
        db.execute(
            select(Badge.entity_id, func.count(Badge.id))
            .where(Badge.entity_type == EntityType.village)
            .group_by(Badge.entity_id)
        ).all()
    )
    rows: List[VillageLeaderboardRow] = []
    for village in villages:
        rows.append(
            VillageLeaderboardRow(
                village_id=village.id,
                block=village.block,
                district=village.district,
                points=int(village_points.get(village.id, 0)) + int(caregiver_points.get(village.id, 0)),
                children_count=int(children_counts.get(village.id, 0)),
                badges=int(badge_counts.get(village.id, 0)),
            )
        )
    return sorted(rows, key=lambda row: (-row.points, row.district, row.block))


def completed_milestones(db: Session, child: Child) -> int:
    schedules = db.scalars(select(VaccineSchedule)).all()
    by_age: Dict[int, set[str]] = {}
    for schedule in schedules:
        by_age.setdefault(schedule.age_due_days, set()).add(schedule.vaccine_code)
    completed_codes = {dose.vaccine_code for dose in child.doses}
    return sum(1 for codes in by_age.values() if codes.issubset(completed_codes))


def current_streak(child: Child) -> int:
    rules = load_rules()
    grace_days = int(rules["caregiver"]["streak_grace_days"])
    ordered = sorted(child.doses, key=lambda dose: dose.given_on)
    if not ordered:
        return 0
    streak = 1
    best = 1
    for previous, current in zip(ordered, ordered[1:]):
        if (current.given_on - previous.given_on).days <= grace_days:
            streak += 1
        else:
            streak = 1
        best = max(best, streak)
    return best


def _caregiver_points(db: Session, child: Child, dose: Dose, event: DoseRecordedEvent, rules: Dict[str, Any]) -> int:
    config = rules["caregiver"]["dose_recorded"]
    dose_timeliness = timeliness(dose)
    total = int(config["catch_up"] if dose_timeliness == "late_catch_up" else config["on_time"])
    if event.paper_card_updated:
        total += int(config["paper_card_updated"])
    if event.verified_referral:
        total += int(config["verified_referral"])
    if _completes_visit_set(db, child, dose):
        total += int(config["whole_visit_set_complete"])
    return max(0, total)


def _asha_points(dose: Dose, event: DoseRecordedEvent, rules: Dict[str, Any]) -> int:
    total = 0
    if dose.synced_at is not None and dose.synced_at.date() == dose.given_on:
        total += int(rules["asha"]["same_day_entry"])
    if event.defaulter_traced:
        total += int(rules["asha"]["defaulter_traced"])
    return total


def _whole_visit_set_bonus(db: Session, child: Child, dose: Dose, rules: Dict[str, Any]) -> int:
    if not _completes_visit_set(db, child, dose):
        return 0
    return int(rules["caregiver"]["dose_recorded"]["whole_visit_set_complete"])


def _completes_visit_set(db: Session, child: Child, dose: Dose) -> bool:
    schedule = db.scalar(select(VaccineSchedule).where(VaccineSchedule.vaccine_code == dose.vaccine_code))
    if schedule is None:
        return False
    required = set(
        db.scalars(select(VaccineSchedule.vaccine_code).where(VaccineSchedule.age_due_days == schedule.age_due_days)).all()
    )
    completed = {record.vaccine_code for record in child.doses}
    return required.issubset(completed)


def _award_badges(db: Session, child: Child, rules: Dict[str, Any]) -> None:
    badge_rules = rules["caregiver"]["badges"]
    completed_codes = {dose.vaccine_code for dose in child.doses}
    completed_ages = _completed_ages(db, child)
    age_days = (date.today() - child.dob).days

    fully = badge_rules["fully_immunised_by_1"]
    if age_days <= int(fully["max_age_days"]) and set(fully["required_milestones_days"]).issubset(completed_ages):
        _add_badge(db, EntityType.child, child.id, str(fully["code"]), str(fully["name"]))

    booster = badge_rules["booster_hero"]
    if set(booster["required_codes"]).issubset(completed_codes):
        _add_badge(db, EntityType.child, child.id, str(booster["code"]), str(booster["name"]))

    if completed_milestones(db, child) >= 3:
        champion = badge_rules["village_champion"]
        _add_badge(db, EntityType.village, child.village_id, str(champion["code"]), str(champion["name"]))


def _completed_ages(db: Session, child: Child) -> set[int]:
    schedules = db.scalars(select(VaccineSchedule)).all()
    by_age: Dict[int, set[str]] = {}
    for schedule in schedules:
        by_age.setdefault(schedule.age_due_days, set()).add(schedule.vaccine_code)
    completed_codes = {dose.vaccine_code for dose in child.doses}
    return {age for age, codes in by_age.items() if codes.issubset(completed_codes)}


def _level_for(completed: int, rules: Dict[str, Any]) -> str:
    level = "Seed"
    for item in rules["caregiver"]["levels"]:
        if completed >= int(item["completed_milestones"]):
            level = str(item["name"])
    return level


def _add_points(db: Session, entity_type: EntityType, entity_id: int, points: int, reason: str) -> Points:
    award = Points(entity_type=entity_type, entity_id=entity_id, points=points, reason=reason)
    db.add(award)
    return award


def _add_badge(db: Session, entity_type: EntityType, entity_id: int, code: str, name: str) -> None:
    existing = db.scalar(
        select(Badge.id).where(
            Badge.entity_type == entity_type,
            Badge.entity_id == entity_id,
            Badge.code == code,
        )
    )
    if existing is None:
        db.add(Badge(entity_type=entity_type, entity_id=entity_id, code=code, name=name))
