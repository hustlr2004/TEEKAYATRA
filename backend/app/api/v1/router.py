from __future__ import annotations

import asyncio
from datetime import date, datetime
from typing import List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from fastapi.routing import APIRoute
from fastapi.responses import HTMLResponse, Response, StreamingResponse

from ...core.security import current_user, user_id_from_token
from ...database import get_db
from ...models import User
from ...schemas.api import ChildCreate, ConsentCreate, GrievanceCreate, LoginRequest, OtpRequest, OtpVerify, RefreshRequest, SimInbound, SyncPush, UserCreate
from ...schemas.query import ListQuery
from ...services.live_events import role_events, sse_lines
from ..dependencies import AppServiceRunner, get_app_service

router = APIRouter()

ERROR_RESPONSES = {
    400: {
        "description": "Bad request",
        "content": {"application/json": {"example": {"code": "bad_request", "message": "Guardian consent required before storing child", "details": {}, "request_id": "req_123"}}},
    },
    401: {
        "description": "Missing or invalid bearer token",
        "content": {"application/json": {"example": {"code": "unauthorized", "message": "Missing bearer token", "details": {}, "request_id": "req_123"}}},
    },
    403: {
        "description": "Authenticated user is not allowed to perform this action",
        "content": {"application/json": {"example": {"code": "forbidden", "message": "Child not accessible", "details": {}, "request_id": "req_123"}}},
    },
    404: {
        "description": "Resource not found",
        "content": {"application/json": {"example": {"code": "not_found", "message": "Child not found", "details": {}, "request_id": "req_123"}}},
    },
    409: {
        "description": "Conflict, usually from idempotency-key reuse or sync conflict",
        "content": {"application/json": {"example": {"code": "conflict", "message": "Idempotency-Key was already used with a different payload", "details": {}, "request_id": "req_123"}}},
    },
    422: {
        "description": "Validation error",
        "content": {
            "application/json": {
                "example": {
                    "code": "validation_error",
                    "message": "Request validation failed",
                    "details": {"errors": [{"loc": ["body", "phone"], "msg": "Field required", "type": "missing"}]},
                    "request_id": "req_123",
                }
            }
        },
    },
    429: {
        "description": "Rate limit exceeded",
        "content": {"application/json": {"example": {"code": "rate_limit_exceeded", "message": "Rate limit exceeded", "details": {}, "request_id": "req_123"}}},
    },
}


ROUTE_DOCS = {
    "health": {
        "tags": ["Platform"],
        "summary": "API liveness check",
        "description": "Returns a fast liveness signal. This route does not check PostgreSQL or Redis.",
        "responses": {200: {"description": "API process is alive", "content": {"application/json": {"example": {"status": "ok"}}}}},
    },
    "auth_token": {
        "tags": ["Authentication"],
        "summary": "Issue demo tokens for a seeded user",
        "description": "Development helper for demos and tests. Use `/auth/login` or OTP in production flows.",
        "responses": {200: {"description": "Bearer and refresh token pair", "content": {"application/json": {"example": {"access_token": "jwt", "refresh_token": "opaque", "token_type": "bearer"}}}}},
    },
    "auth_login": {"tags": ["Authentication"], "summary": "Login with phone and password", "description": "Authenticates a user and starts a refresh-token family with rotation."},
    "auth_refresh": {"tags": ["Authentication"], "summary": "Rotate a refresh token", "description": "Revokes the presented refresh token and returns a fresh access/refresh pair."},
    "auth_logout": {"tags": ["Authentication"], "summary": "Revoke a refresh token", "description": "Marks the refresh token as revoked so it cannot be reused."},
    "auth_otp_request": {"tags": ["Authentication"], "summary": "Request a mock OTP", "description": "Creates an expiring OTP challenge with attempt limits. The demo response includes the code."},
    "auth_otp_verify": {"tags": ["Authentication"], "summary": "Verify OTP and login", "description": "Consumes a valid OTP challenge and returns an access/refresh token pair."},
    "create_user": {"tags": ["Admin"], "summary": "Create a user", "description": "Admin-only user creation. Phone numbers are encrypted at rest and masked in responses."},
    "list_users": {"tags": ["Admin"], "summary": "List users", "description": "Admin-only paginated user listing with optional role and text filters."},
    "list_villages": {"tags": ["Reference Data"], "summary": "List villages", "description": "Returns village reference data with block and district filters."},
    "list_schedule": {"tags": ["Reference Data"], "summary": "List vaccine schedule", "description": "Returns the India immunization schedule stored as data, including endemic-only flags and grace windows."},
    "demo_summary": {"tags": ["Platform"], "summary": "Demo data summary", "description": "Counts core records so demo operators can confirm seed data loaded."},
    "capture_consent": {"tags": ["Consent & Privacy"], "summary": "Capture guardian consent", "description": "Stores consent for a named purpose before child data capture or reminders."},
    "withdraw_consent": {"tags": ["Consent & Privacy"], "summary": "Withdraw consent", "description": "Marks an existing consent as withdrawn without deleting the audit history."},
    "create_child": {"tags": ["Children"], "summary": "Register a child", "description": "Creates a child record only after active guardian consent. Caregivers can register only their own children."},
    "list_children": {"tags": ["Children"], "summary": "List accessible children", "description": "Caregivers see own children, ASHAs see assigned village children, and managers receive aggregated rows only."},
    "blank_card_template_pdf": {"tags": ["Vaccination Cards"], "summary": "Download a blank card PDF", "description": "Returns a bilingual printable A5 vaccination card template."},
    "get_child": {"tags": ["Children"], "summary": "Get a child record", "description": "Returns one child when row-level authorization allows it. Reads are audited."},
    "child_schedule": {"tags": ["Schedule"], "summary": "Get a child's schedule", "description": "Computes due, overdue, catch-up, and next-visit details from the VaccineSchedule table."},
    "child_progress": {"tags": ["Gamification"], "summary": "Get child progress", "description": "Returns points, level, streak, badges, and milestone progress for the Suraksha Tree."},
    "child_card_pdf": {"tags": ["Vaccination Cards"], "summary": "Download a child's card PDF", "description": "Returns a filled printable record card with QR code containing only the child ID."},
    "delete_my_data": {"tags": ["Consent & Privacy"], "summary": "Delete my caregiver data", "description": "Caregiver self-service deletion flow for child records owned by the caregiver."},
    "export_my_data": {"tags": ["Consent & Privacy"], "summary": "Export my caregiver data", "description": "Caregiver self-service export of minimized personal and child records."},
    "create_grievance": {"tags": ["Consent & Privacy"], "summary": "File a grievance", "description": "Creates a grievance for consent, access, reminder, or data-rights concerns."},
    "list_grievances": {"tags": ["Admin"], "summary": "List grievances", "description": "Admin-only grievance queue with pagination and status filter."},
    "data_retention_job": {"tags": ["Admin"], "summary": "Run data-retention cleanup", "description": "Admin-only manual trigger for the retention cleanup job."},
    "village_leaderboard": {"tags": ["Gamification"], "summary": "Village leaderboard", "description": "Aggregated team/village leaderboard only. Payloads never include child names or phone numbers."},
    "manager_analytics": {"tags": ["Analytics"], "summary": "Manager dashboard analytics", "description": "Aggregated coverage, dropout, timeliness, risk, anomaly, and triangulation metrics with filters."},
    "admin_jobs": {"tags": ["Admin"], "summary": "Background job status", "description": "Admin-only status for background jobs, retries, and dead-letter records."},
    "events": {"tags": ["Live Events"], "summary": "Role-scoped server-sent events", "description": "Authenticated SSE stream for live caregiver tree growth and manager dashboard updates. Supports `Last-Event-ID` reconnects."},
    "feature_phone_sim": {"tags": ["Notifications"], "summary": "Feature-phone inbox simulator", "description": "Demo page that displays SMS/IVR reminder logs as a feature-phone inbox."},
    "sim_inbound": {"tags": ["Notifications"], "summary": "Process inbound SMS", "description": "Processes mock inbound SMS such as STOP for opt-out."},
    "sim_inbound_query": {"tags": ["Notifications"], "summary": "Process inbound SMS from the demo page", "description": "HTML-friendly mock inbound SMS handler for the feature-phone simulator."},
    "sync_push": {"tags": ["Offline Sync"], "summary": "Push offline changes", "description": "Accepts a batch with an `Idempotency-Key`, returns per-item results, unions doses, and queues conflicts for ASHA review."},
    "sync_pull": {"tags": ["Offline Sync"], "summary": "Pull server changes", "description": "Returns accessible children and monotonic change-log entries after the supplied cursor."},
    "sync_conflicts": {"tags": ["Offline Sync"], "summary": "List sync conflicts", "description": "ASHA/admin conflict review queue for duplicate doses and out-of-order child updates."},
}


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


def _apply_route_docs() -> None:
    for route in router.routes:
        if not isinstance(route, APIRoute):
            continue
        metadata = ROUTE_DOCS.get(route.endpoint.__name__)
        if metadata is None:
            continue
        route.tags = metadata.get("tags", route.tags)
        route.summary = metadata.get("summary", route.summary)
        route.description = metadata.get("description", route.description)
        route.responses = {**ERROR_RESPONSES, **metadata.get("responses", {})}


_apply_route_docs()


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
