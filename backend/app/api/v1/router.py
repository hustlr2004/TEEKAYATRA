from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from ...core.security import current_user, user_id_from_token
from ...database import get_db
from ...models import User
from ...schemas.api import ChildCreate, ConsentCreate, GrievanceCreate, LoginRequest, OtpRequest, OtpVerify, RefreshRequest, SimInbound, SyncPush, UserCreate
from ...schemas.query import ListQuery
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


@router.post("/auth/refresh")
async def auth_refresh(payload: RefreshRequest, service: AppServiceRunner = Depends(get_app_service)) -> dict[str, str]:
    return await service.run(lambda app: app.refresh(payload))


@router.post("/auth/logout")
async def auth_logout(payload: RefreshRequest, service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.logout(payload))


@router.post("/auth/otp/request")
async def auth_otp_request(payload: OtpRequest, service: AppServiceRunner = Depends(get_app_service)) -> dict[str, object]:
    return await service.run(lambda app: app.request_otp(payload))


@router.post("/auth/otp/verify")
async def auth_otp_verify(payload: OtpVerify, service: AppServiceRunner = Depends(get_app_service)) -> dict[str, str]:
    return await service.run(lambda app: app.verify_otp(payload))


@router.post("/users", status_code=status.HTTP_201_CREATED)
async def create_user(
    payload: UserCreate,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.create_user(payload, actor))


@router.get("/users")
async def list_users(
    page: int = 1,
    page_size: int = 100,
    sort: str = "id",
    order: str = "asc",
    q: Optional[str] = None,
    role: Optional[str] = None,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_users(actor, _list_query(page, page_size, sort, order, q=q, role=role)))


@router.get("/villages")
async def list_villages(
    page: int = 1,
    page_size: int = 100,
    sort: str = "district",
    order: str = "asc",
    q: Optional[str] = None,
    block: Optional[str] = None,
    district: Optional[str] = None,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_villages(_list_query(page, page_size, sort, order, q=q, block=block, district=district)))


@router.get("/schedule")
async def list_schedule(
    page: int = 1,
    page_size: int = 100,
    sort: str = "age_due_days",
    order: str = "asc",
    q: Optional[str] = None,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_schedule(_list_query(page, page_size, sort, order, q=q)))


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
async def list_children(
    page: int = 1,
    page_size: int = 100,
    sort: str = "id",
    order: str = "asc",
    q: Optional[str] = None,
    block: Optional[str] = None,
    district: Optional[str] = None,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_children(actor, _list_query(page, page_size, sort, order, q=q, block=block, district=district)))


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
async def list_grievances(
    page: int = 1,
    page_size: int = 100,
    sort: str = "id",
    order: str = "asc",
    q: Optional[str] = None,
    status: Optional[str] = None,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> List[dict[str, object]]:
    return await service.run(lambda app: app.list_grievances(actor, _list_query(page, page_size, sort, order, q=q, status=status)))


@router.post("/jobs/data-retention")
async def data_retention_job(actor: User = Depends(current_user), service: AppServiceRunner = Depends(get_app_service)) -> dict[str, int]:
    return await service.run(lambda app: app.data_retention_job(actor))


@router.get("/leaderboard/village")
async def village_leaderboard(
    page: int = 1,
    page_size: int = 100,
    sort: str = "points",
    order: str = "desc",
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> List[dict[str, object]]:
    return await service.run(lambda app: app.village_leaderboard(actor, _list_query(page, page_size, sort, order)))


@router.get("/analytics/manager")
async def manager_analytics(
    block: Optional[str] = None,
    district: Optional[str] = None,
    start_date: Optional[date] = None,
    end_date: Optional[date] = None,
    page: int = 1,
    page_size: int = 50,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.manager_analytics(actor, block, district, start_date, end_date, page, page_size))


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
    idempotency_key: str = Header(..., alias="Idempotency-Key"),
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.sync_push(payload, actor, idempotency_key))


@router.get("/sync/pull")
async def sync_pull(
    cursor: int = 0,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> dict[str, object]:
    return await service.run(lambda app: app.sync_pull(cursor, actor))


@router.get("/sync/conflicts")
async def sync_conflicts(
    page: int = 1,
    page_size: int = 100,
    sort: str = "created_at",
    order: str = "asc",
    status: Optional[str] = None,
    actor: User = Depends(current_user),
    service: AppServiceRunner = Depends(get_app_service),
) -> List[dict[str, object]]:
    return await service.run(lambda app: app.conflict_review_queue(actor, _list_query(page, page_size, sort, order, status=status)))


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


def _list_query(
    page: int,
    page_size: int,
    sort: str,
    order: str,
    q: Optional[str] = None,
    role: Optional[str] = None,
    block: Optional[str] = None,
    district: Optional[str] = None,
    status: Optional[str] = None,
) -> ListQuery:
    return ListQuery(page=page, page_size=page_size, sort=sort, order=order, q=q, role=role, block=block, district=district, status=status)
