from __future__ import annotations

import logging
import uuid
import hashlib
from time import time
from typing import Any, Dict, List

import redis
import jwt
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.responses import JSONResponse, Response
from sqlalchemy import func, select, text
from slowapi import Limiter
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from .api.v1.router import router as v1_router
from .core.config import get_settings
from .core.logging import configure_logging, request_id_var
from .core.metrics import job_queue_length, render_metrics, request_errors_total, request_latency_seconds
from .database import SessionLocal, engine
from .models import JobRun, JobStatus

settings = get_settings()
RATE_LIMIT_WINDOW_SECONDS = settings.rate_limit_window_seconds
RATE_LIMIT_MAX_REQUESTS = settings.rate_limit_max_requests
configure_logging()
logger = logging.getLogger("teeka.api")

app = FastAPI(title="Teeka Yatra API", version="0.1.0")
limiter = Limiter(key_func=get_remote_address, storage_uri=settings.rate_limit_storage_uri, default_limits=["120/minute"])
app.state.limiter = limiter
app.add_middleware(GZipMiddleware, minimum_size=500)


@app.exception_handler(RateLimitExceeded)
async def slowapi_rate_limit_handler(request: Request, exc: RateLimitExceeded):
    return _error_response(request, "rate_limit_exceeded", "Rate limit exceeded", 429)


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return _error_response(request, _code_for_status(exc.status_code), str(exc.detail), exc.status_code)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    return _error_response(request, "validation_error", "Request validation failed", 422, _validation_details(exc))


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled request error")
    return _error_response(request, "internal_error", "Internal server error", 500)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "Idempotency-Key", "Last-Event-ID"],
)

_rate_limit_buckets: Dict[str, List[float]] = {}


@app.middleware("http")
async def observability_and_security(request: Request, call_next):
    request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex
    token = request_id_var.set(request_id)
    started = time()
    if request.url.path in {"/health", "/api/v1/health"}:
        response = await call_next(request)
    else:
        client = request.client.host if request.client is not None else "unknown"
        auth = request.headers.get("authorization", "")
        user_part = _rate_limit_subject(auth)
        key = "%s:%s:%s" % (client, user_part, request.url.path)
        now = time()
        bucket = [
            stamp
            for stamp in _rate_limit_buckets.get(key, [])
            if now - stamp < RATE_LIMIT_WINDOW_SECONDS
        ]
        if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
            response = _error_response(request, "rate_limit_exceeded", "Rate limit exceeded", 429)
        else:
            bucket.append(now)
            _rate_limit_buckets[key] = bucket
            response = await call_next(request)
    duration = time() - started
    status_code = getattr(response, "status_code", 500)
    path = _metric_path(request)
    request_latency_seconds.labels(request.method, path, str(status_code)).observe(duration)
    if status_code >= 400:
        request_errors_total.labels(request.method, path, str(status_code)).inc()
    if _etag_safe(request, response):
        body = b""
        async for chunk in response.body_iterator:
            body += chunk
        etag = hashlib.sha256(body).hexdigest()
        if request.headers.get("if-none-match") == etag:
            response = Response(status_code=304)
        else:
            response = Response(content=body, status_code=status_code, headers=dict(response.headers), media_type=response.media_type)
            response.headers["ETag"] = etag
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    response.headers["Content-Security-Policy"] = "default-src 'self'"
    logger.info(
        "request completed",
        extra={"method": request.method, "path": path, "status_code": status_code, "duration_ms": round(duration * 1000, 2)},
    )
    request_id_var.reset(token)
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}


@app.get("/ready")
async def ready() -> JSONResponse:
    checks = {"db": await _check_db(), "redis": _check_redis()}
    ok = all(checks.values())
    return JSONResponse(status_code=200 if ok else 503, content={"status": "ok" if ok else "not_ready", "checks": checks})


@app.get("/metrics")
async def metrics() -> Response:
    await _refresh_job_queue_metric()
    body, media_type = render_metrics()
    return Response(content=body, media_type=media_type)


app.include_router(v1_router, prefix="/api/v1")
app.include_router(v1_router)


def _error_response(
    request: Request,
    code: str,
    message: str,
    status_code: int,
    details: Any | None = None,
) -> JSONResponse:
    request_id = request_id_var.get()
    return JSONResponse(
        status_code=status_code,
        content={"code": code, "message": message, "details": details or {}, "request_id": request_id},
    )


def _code_for_status(status_code: int) -> str:
    return {
        400: "bad_request",
        401: "unauthorized",
        403: "forbidden",
        404: "not_found",
        409: "conflict",
        422: "validation_error",
        423: "locked",
        429: "rate_limit_exceeded",
    }.get(status_code, "http_error")


def _validation_details(exc: RequestValidationError) -> dict[str, object]:
    return {"errors": [{"loc": list(error["loc"]), "msg": error["msg"], "type": error["type"]} for error in exc.errors()]}


def _metric_path(request: Request) -> str:
    route = request.scope.get("route")
    return getattr(route, "path", request.url.path)


def _etag_safe(request: Request, response: Response) -> bool:
    if request.method != "GET" or response.status_code != 200:
        return False
    path = request.url.path
    if path.endswith(".pdf") or path in {"/events", "/metrics"}:
        return False
    content_type = response.headers.get("content-type", "")
    return "application/json" in content_type


def _rate_limit_subject(authorization: str) -> str:
    if not authorization.lower().startswith("bearer "):
        return "anonymous"
    try:
        payload = jwt.decode(authorization.split(" ", 1)[1], options={"verify_signature": False})
        return "user:%s" % payload.get("sub", "unknown")
    except Exception:
        return "invalid-token"


async def _check_db() -> bool:
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:
        logger.warning("readiness db check failed")
        return False


def _check_redis() -> bool:
    try:
        client = redis.Redis.from_url(settings.redis_url, socket_connect_timeout=0.2, socket_timeout=0.2)
        return bool(client.ping())
    except Exception:
        logger.warning("readiness redis check failed")
        return False


async def _refresh_job_queue_metric() -> None:
    try:
        async with SessionLocal() as db:
            count = await db.scalar(select(func.count(JobRun.id)).where(JobRun.status == JobStatus.running))
            job_queue_length.set(count or 0)
    except Exception:
        job_queue_length.set(0)
