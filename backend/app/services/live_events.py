from __future__ import annotations

import json
from typing import Dict, Iterable, List, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Child, Dose, OutboxEvent, Role, User
from .event_bus import DOSE_RECORDED


def role_events(db: Session, actor: User, since_id: int) -> List[dict[str, object]]:
    events = db.scalars(
        select(OutboxEvent)
        .where(OutboxEvent.id > since_id, OutboxEvent.event_type == DOSE_RECORDED)
        .order_by(OutboxEvent.id)
    ).all()
    return [payload for payload in (_event_for_actor(db, event, actor) for event in events) if payload is not None]


def sse_lines(events: Iterable[dict[str, object]]) -> str:
    chunks: List[str] = []
    for event in events:
        chunks.append("id: %s" % event["id"])
        chunks.append("event: %s" % event["event"])
        chunks.append("data: %s" % json.dumps(event["data"], default=str))
        chunks.append("")
    return "\n".join(chunks) + ("\n" if chunks else "")


def _event_for_actor(db: Session, event: OutboxEvent, actor: User) -> Optional[dict[str, object]]:
    payload = json.loads(event.payload)
    child = db.get(Child, int(payload["child_id"]))
    if child is None:
        return None

    if actor.role == Role.caregiver:
        if child.guardian_id != actor.id:
            return None
        return {
            "id": event.id,
            "event": "caregiver.tree",
            "data": {
                "type": "tree_grew",
                "child_id": child.id,
                "dose_id": int(payload["dose_id"]),
                "vaccine_code": payload["vaccine_code"],
            },
        }

    if actor.role == Role.asha:
        if child.village_id != actor.village_id:
            return None
        return {
            "id": event.id,
            "event": "asha.dose_recorded",
            "data": {
                "type": "dose_recorded",
                "child_id": child.id,
                "vaccine_code": payload["vaccine_code"],
            },
        }

    if actor.role in {Role.manager, Role.admin}:
        dose = db.get(Dose, int(payload["dose_id"]))
        return {
            "id": event.id,
            "event": "manager.dashboard",
            "data": {
                "type": "dashboard_counters_updated",
                "village_id": child.village_id,
                "vaccine_code": payload["vaccine_code"],
                "given_on": dose.given_on.isoformat() if dose is not None else payload["given_on"],
            },
        }

    return None
