from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Dict, Iterable, List, Optional


SCHEDULE_PATH = Path(__file__).with_name("immunization_schedule.json")


@dataclass(frozen=True)
class Vaccine:
    code: str
    name: str
    endemic_only: bool = False


@dataclass(frozen=True)
class ScheduleWindow:
    id: str
    label: str
    start_days: int
    end_days: int
    vaccines: List[Vaccine]


@dataclass(frozen=True)
class DoseDue:
    code: str
    name: str
    window_id: str
    window_label: str
    due_from: date
    due_until: date
    status: str
    catch_up_bonus: bool


def _parse_window(raw: Dict[str, object]) -> ScheduleWindow:
    vaccines = [
        Vaccine(
            code=str(item["code"]),
            name=str(item["name"]),
            endemic_only=bool(item.get("endemic_only", False)),
        )
        for item in raw["vaccines"]  # type: ignore[index]
    ]
    return ScheduleWindow(
        id=str(raw["id"]),
        label=str(raw["label"]),
        start_days=int(raw["start_days"]),
        end_days=int(raw["end_days"]),
        vaccines=vaccines,
    )


@lru_cache(maxsize=1)
def load_schedule() -> List[ScheduleWindow]:
    raw = json.loads(SCHEDULE_PATH.read_text(encoding="utf-8"))
    return [_parse_window(item) for item in raw]


def vitamin_a_followups() -> List[ScheduleWindow]:
    windows: List[ScheduleWindow] = []
    start_days = 487
    for dose_number in range(3, 10):
        due_days = start_days + ((dose_number - 2) * 183)
        windows.append(
            ScheduleWindow(
                id="vitamin_a_%s" % dose_number,
                label="Vitamin A dose %s" % dose_number,
                start_days=due_days,
                end_days=min(due_days + 30, 1826),
                vaccines=[
                    Vaccine(
                        code="VITA_%s" % dose_number,
                        name="Vitamin A dose %s" % dose_number,
                    )
                ],
            )
        )
    return windows


def expanded_schedule() -> List[ScheduleWindow]:
    windows = list(load_schedule())
    windows.extend(vitamin_a_followups())
    return sorted(windows, key=lambda item: item.start_days)


def due_doses(
    birth_date: date,
    today: date,
    completed_codes: Iterable[str],
    district_is_je_endemic: bool,
) -> List[DoseDue]:
    completed = set(completed_codes)
    doses: List[DoseDue] = []
    for window in expanded_schedule():
        due_from = birth_date + timedelta(days=window.start_days)
        due_until = birth_date + timedelta(days=window.end_days)
        for vaccine in window.vaccines:
            if vaccine.endemic_only and not district_is_je_endemic:
                continue
            if vaccine.code in completed:
                status = "completed"
            elif today < due_from:
                status = "upcoming"
            elif today <= due_until:
                status = "due"
            else:
                status = "catch_up"
            doses.append(
                DoseDue(
                    code=vaccine.code,
                    name=vaccine.name,
                    window_id=window.id,
                    window_label=window.label,
                    due_from=due_from,
                    due_until=due_until,
                    status=status,
                    catch_up_bonus=status == "catch_up",
                )
            )
    return doses


def next_due(doses: Iterable[DoseDue]) -> Optional[DoseDue]:
    actionable = [dose for dose in doses if dose.status in {"due", "catch_up", "upcoming"}]
    if not actionable:
        return None
    return sorted(actionable, key=lambda dose: (dose.due_from, dose.code))[0]
