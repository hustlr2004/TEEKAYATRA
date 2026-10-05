from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import List, Optional

from sqlalchemy import select
from sqlalchemy.orm import object_session

from ..models import Child, Dose, VaccineSchedule


JE_ENDEMIC_DISTRICTS = {
    "Endemic District",
    "Patna",
}


@dataclass(frozen=True)
class DoseWindow:
    vaccine_code: str
    name: str
    due_on: date
    due_until: date
    status: str
    endemic_only: bool
    given_on: Optional[date] = None
    timeliness: Optional[str] = None


@dataclass(frozen=True)
class VisitPlan:
    visit_on: Optional[date]
    status: str
    vaccines: List[DoseWindow]


def due_doses(child: Child, today: date) -> List[DoseWindow]:
    return [
        window
        for window in schedule_windows(child, today)
        if window.given_on is None and window.due_on <= today
    ]


def overdue_doses(child: Child, today: date) -> List[DoseWindow]:
    return [
        window
        for window in schedule_windows(child, today)
        if window.given_on is None and today > window.due_until
    ]


def next_visit(child: Child) -> VisitPlan:
    today = date.today()
    pending = [window for window in schedule_windows(child, today) if window.given_on is None]
    if not pending:
        return VisitPlan(visit_on=None, status="complete", vaccines=[])

    actionable = [window for window in pending if window.due_on <= today]
    if actionable:
        return VisitPlan(visit_on=today, status="catch_up", vaccines=actionable)

    next_due = min(window.due_on for window in pending)
    return VisitPlan(
        visit_on=next_due,
        status="upcoming",
        vaccines=[window for window in pending if window.due_on == next_due],
    )


def timeliness(dose: Dose) -> str:
    session = object_session(dose)
    if session is None:
        raise ValueError("Dose must be attached to a database session")
    schedule = session.scalar(select(VaccineSchedule).where(VaccineSchedule.vaccine_code == dose.vaccine_code))
    if schedule is None:
        return "unknown"

    due_on = dose.child.dob + timedelta(days=schedule.age_due_days)
    due_until = due_on + timedelta(days=schedule.window_days)
    if dose.given_on < due_on:
        return "early"
    if dose.given_on == due_on:
        return "on_time"
    if dose.given_on <= due_until:
        return "grace"
    return "late_catch_up"


def schedule_windows(child: Child, today: date) -> List[DoseWindow]:
    schedules = _schedules_for_child(child)
    doses_by_code = {dose.vaccine_code: dose for dose in child.doses}
    windows: List[DoseWindow] = []
    for schedule in schedules:
        dose = doses_by_code.get(schedule.vaccine_code)
        due_on = child.dob + timedelta(days=schedule.age_due_days)
        due_until = due_on + timedelta(days=schedule.window_days)
        if dose is not None:
            windows.append(
                DoseWindow(
                    vaccine_code=schedule.vaccine_code,
                    name=schedule.name,
                    due_on=due_on,
                    due_until=due_until,
                    status="completed",
                    endemic_only=schedule.endemic_only,
                    given_on=dose.given_on,
                    timeliness=timeliness(dose),
                )
            )
            continue

        windows.append(
            DoseWindow(
                vaccine_code=schedule.vaccine_code,
                name=schedule.name,
                due_on=due_on,
                due_until=due_until,
                status=_pending_status(due_on, due_until, today),
                endemic_only=schedule.endemic_only,
            )
        )
    return sorted(windows, key=lambda window: (window.due_on, window.vaccine_code))


def _pending_status(due_on: date, due_until: date, today: date) -> str:
    if today < due_on:
        return "upcoming"
    if today <= due_until:
        return "due"
    return "catch_up"


def _schedules_for_child(child: Child) -> List[VaccineSchedule]:
    session = object_session(child)
    if session is None:
        raise ValueError("Child must be attached to a database session")
    schedules = list(session.scalars(select(VaccineSchedule).order_by(VaccineSchedule.age_due_days, VaccineSchedule.vaccine_code)).all())
    return [
        schedule
        for schedule in schedules
        if not schedule.endemic_only or _is_je_endemic(child)
    ]


def _is_je_endemic(child: Child) -> bool:
    return child.village is not None and child.village.district in JE_ENDEMIC_DISTRICTS
