from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime
from typing import Callable, Dict, List

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import AuditLog, Dose, EventDelivery, EventStatus, OutboxEvent
from .audit import audit_child_access
from .cache import invalidate_analytics_cache
from .gamification import DoseRecordedEvent, on_dose_recorded
from .schedule import next_visit

DOSE_RECORDED = "DoseRecorded"


@dataclass(frozen=True)
class EventProcessingResult:
    event_id: int
    delivered: List[str]
    skipped: List[str]


Subscriber = Callable[[Session, OutboxEvent], None]


def publish_dose_recorded(
    db: Session,
    dose: Dose,
    *,
    paper_card_updated: bool = False,
    verified_referral: bool = False,
    defaulter_traced: bool = False,
) -> OutboxEvent:
    payload = {
        "dose_id": dose.id,
        "child_id": dose.child_id,
        "recorded_by": dose.recorded_by,
        "vaccine_code": dose.vaccine_code,
        "given_on": dose.given_on.isoformat(),
        "paper_card_updated": paper_card_updated,
        "verified_referral": verified_referral,
        "defaulter_traced": defaulter_traced,
    }
    event = OutboxEvent(
        event_type=DOSE_RECORDED,
        aggregate_type="dose",
        aggregate_id=str(dose.id),
        payload=json.dumps(payload),
        status=EventStatus.pending,
    )
    db.add(event)
    return event


def process_outbox(db: Session) -> List[EventProcessingResult]:
    events = db.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.status.in_([EventStatus.pending, EventStatus.failed]))
        .order_by(OutboxEvent.id)
    ).all()
    return [process_event(db, event) for event in events]


def process_event(db: Session, event: OutboxEvent) -> EventProcessingResult:
    if event.event_type != DOSE_RECORDED:
        return EventProcessingResult(event.id, [], [])

    delivered: List[str] = []
    skipped: List[str] = []
    event.status = EventStatus.processing
    event.attempts += 1
    db.flush()

    for name, subscriber in dose_recorded_subscribers().items():
        delivery = _delivery_for(db, event.id, name)
        if delivery.status == EventStatus.processed:
            skipped.append(name)
            continue
        delivery.status = EventStatus.processing
        delivery.attempts += 1
        delivery.error = None
        db.flush()
        try:
            subscriber(db, event)
        except Exception as exc:
            delivery.status = EventStatus.failed
            delivery.error = str(exc)
            event.status = EventStatus.failed
            event.error = "%s: %s" % (name, exc)
            db.flush()
            raise
        delivery.status = EventStatus.processed
        delivery.processed_at = datetime.utcnow()
        delivered.append(name)
        db.flush()

    event.status = EventStatus.processed
    event.error = None
    event.processed_at = datetime.utcnow()
    db.flush()
    return EventProcessingResult(event.id, delivered, skipped)


def dose_recorded_subscribers() -> Dict[str, Subscriber]:
    return {
        "gamification_points": _handle_gamification_points,
        "badge_checks": _handle_badge_checks,
        "next_visit_calculation": _handle_next_visit_calculation,
        "reminder_rescheduling": _handle_reminder_rescheduling,
        "analytics_counters": _handle_analytics_counters,
        "audit_log": _handle_audit_log,
    }


def _delivery_for(db: Session, event_id: int, subscriber: str) -> EventDelivery:
    delivery = db.scalar(
        select(EventDelivery).where(
            EventDelivery.event_id == event_id,
            EventDelivery.subscriber == subscriber,
        )
    )
    if delivery is None:
        delivery = EventDelivery(event_id=event_id, subscriber=subscriber, status=EventStatus.pending)
        db.add(delivery)
        db.flush()
    return delivery


def _dose_event(db: Session, event: OutboxEvent) -> tuple[Dose, dict[str, object]]:
    payload = json.loads(event.payload)
    dose = db.get(Dose, int(payload["dose_id"]))
    if dose is None:
        raise ValueError("Dose %s not found for event %s" % (payload["dose_id"], event.id))
    return dose, payload


def _handle_gamification_points(db: Session, event: OutboxEvent) -> None:
    dose, payload = _dose_event(db, event)
    on_dose_recorded(
        db,
        DoseRecordedEvent(
            dose=dose,
            paper_card_updated=bool(payload.get("paper_card_updated")),
            verified_referral=bool(payload.get("verified_referral")),
            defaulter_traced=bool(payload.get("defaulter_traced")),
        ),
    )


def _handle_badge_checks(db: Session, event: OutboxEvent) -> None:
    dose, _payload = _dose_event(db, event)
    db.add(
        AuditLog(
            actor_id=dose.recorded_by,
            action="event",
            resource_type="badge",
            resource_id=str(dose.child_id),
            purpose="badge checks after dose recorded",
        )
    )


def _handle_next_visit_calculation(db: Session, event: OutboxEvent) -> None:
    dose, _payload = _dose_event(db, event)
    visit = next_visit(dose.child)
    db.add(
        AuditLog(
            actor_id=dose.recorded_by,
            action="event",
            resource_type="next_visit",
            resource_id=str(dose.child_id),
            purpose="next visit %s on %s" % (visit.status, visit.visit_on.isoformat() if isinstance(visit.visit_on, date) else "none"),
        )
    )


def _handle_reminder_rescheduling(db: Session, event: OutboxEvent) -> None:
    dose, _payload = _dose_event(db, event)
    db.add(
        AuditLog(
            actor_id=dose.recorded_by,
            action="event",
            resource_type="reminder_schedule",
            resource_id=str(dose.child_id),
            purpose="reschedule reminders after dose recorded",
        )
    )


def _handle_analytics_counters(db: Session, event: OutboxEvent) -> None:
    dose, _payload = _dose_event(db, event)
    invalidate_analytics_cache()
    db.add(
        AuditLog(
            actor_id=dose.recorded_by,
            action="event",
            resource_type="analytics",
            resource_id=str(dose.child_id),
            purpose="analytics counters invalidated after dose recorded",
        )
    )


def _handle_audit_log(db: Session, event: OutboxEvent) -> None:
    dose, _payload = _dose_event(db, event)
    audit_child_access(db, dose.recorded_by, "write", dose.child_id, "dose recorded event processed")
