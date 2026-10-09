from __future__ import annotations

import asyncio
from datetime import datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from ...core.security import current_user, user_id_from_token
from ...database import get_db
from ...models import User
from ...schemas.api import ChildCreate, ConsentCreate, GrievanceCreate, LoginRequest, SimInbound, SyncPush, UserCreate
from ...services.live_events import role_events, sse_lines
from ..dependencies import AppServiceRunner, get_app_service

router = APIRouter()


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}


@router.post("/auth/token")
async def auth_token(user_id: int, service: AppServiceRunner = Depends(get_app_service)) -> dict[str, str]:
    return await service.run(lambda app: app.token_for_user_id(user_id))


@router.post("/auth/login")
async def auth_login(payload: LoginRequest, service: AppServiceRunner = Depends(get_app_service)) -> dict[str, str]:
    return await service.run(lambda app: app.login(payload))


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.create_user(payload, actor))


@router.get("/users")
async def list_users(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_users(actor))


@router.get("/villages")
async def list_villages(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_villages())


@router.get("/schedule")
async def list_schedule(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_schedule())


@router.get("/demo-summary")
async def demo_summary(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, int]:
    return await service.run(lambda app: app.demo_summary())


@router.post("/consents", status_code=status.HTTP_201_CREATED)
async def capture_consent(
    payload: ConsentCreate,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.capture_consent(payload, actor))


@router.post("/consents/{consent_id}/withdraw")
async def withdraw_consent(
    consent_id: int,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.withdraw_consent(consent_id, actor))


@router.post("/children", status_code=status.HTTP_201_CREATED)
async def create_child(
    payload: ChildCreate,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.create_child(payload, actor))


@router.get("/children")
async def list_children(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_children(actor))


@router.get("/children/card-template.pdf")
async def blank_card_template_pdf(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> Response:
    return await service.run(lambda app: app.blank_card_pdf(actor))


@router.get("/children/{child_id}")
async def get_child(child_id: int, actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.get_child(child_id, actor))


@router.get("/children/{child_id}/schedule")
async def child_schedule(child_id: int, actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.child_schedule(child_id, actor))


@router.get("/children/{child_id}/progress")
async def child_progress(child_id: int, actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.child_progress(child_id, actor))


@router.get("/children/{child_id}/card.pdf")
async def child_card_pdf(child_id: int, actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> Response:
    return await service.run(lambda app: app.child_card_pdf(child_id, actor))


@router.delete("/me/data")
async def delete_my_data(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.delete_my_data(actor))


@router.get("/me/data/export")
async def export_my_data(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.export_my_data(actor))


@router.post("/grievances", status_code=status.HTTP_201_CREATED)
async def create_grievance(
    payload: GrievanceCreate,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.create_grievance(payload, actor))


@router.get("/grievances")
async def list_grievances(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_grievances(actor))


@router.post("/jobs/data-retention")
async def data_retention_job(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, int]:
    return await service.run(lambda app: app.data_retention_job(actor))


@router.get("/leaderboard/village")
async def village_leaderboard(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> List[dict[str, object]]:
    return await service.run(lambda app: app.village_leaderboard(actor))


@router.get("/analytics/manager")
async def manager_analytics(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.manager_analytics(actor))


@router.get("/admin/jobs")
async def admin_jobs(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.job_status(actor))


@router.get("/events")
async def events(
    request: Request,
    token: Optional[str] = None,
    since: Optional[int] = None,
    once: bool = False,
    last_event_id: Optional[str] = Header(default=None, alias="Last-Event-ID"),
    db=Depends(get_db),
) -> StreamingResponse:
    actor = await _event_stream_user(db, request, token)
    start_id = _event_start_id(last_event_id, since)

    async def stream():
        nonlocal start_id
        while True:
            events_for_actor = await _role_events(db, actor, start_id)
            if events_for_actor:
                start_id = max(int(event["id"]) for event in events_for_actor)
                yield sse_lines(events_for_actor)
            if once:
                break
            yield ": keep-alive\n\n"
            await asyncio.sleep(2)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/sim", response_class=HTMLResponse)
async def feature_phone_sim(service: AppServiceRunner = Depends(get_app_service)) -> str:
    return await service.run(lambda app: app.feature_phone_sim())


@router.post("/sim/inbound")
async def sim_inbound(payload: SimInbound, service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.sim_inbound(payload.phone, payload.message))


@router.get("/sim/inbound")
async def sim_inbound_query(phone: str, message: str = "STOP", service: AppServiceRunner = Depends(get_app_service)) -> HTMLResponse:
    return HTMLResponse(await service.run(lambda app: app.sim_inbound_html(phone, message)))


@router.post("/sync/push")
async def sync_push(
    payload: SyncPush,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.sync_push(payload, actor))


@router.get("/sync/pull")
async def sync_pull(
    since: Optional[datetime] = None,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.sync_pull(since, actor))


async def _event_stream_user(db, request: Request, token: Optional[str]) -> User:
    bearer = request.headers.get("authorization", "")
    raw_token = token
    if bearer.lower().startswith("bearer "):
        raw_token = bearer.split(" ", 1)[1]
    if not raw_token:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token")
    user_id = user_id_from_token(raw_token)
    if hasattr(db, "run_sync"):
        user = await db.run_sync(lambda sync_db: sync_db.get(User, user_id))
    else:
        user = db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unknown user")
    return user


def _event_start_id(last_event_id: Optional[str], since: Optional[int]) -> int:
    if last_event_id:
        try:
            return int(last_event_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Last-Event-ID must be an integer")
    return since or 0


async def _role_events(db, actor: User, since_id: int) -> List[dict[str, object]]:
    if hasattr(db, "run_sync"):
        return await db.run_sync(lambda sync_db: role_events(sync_db, actor, since_id))
    return role_events(db, actor, since_id)
