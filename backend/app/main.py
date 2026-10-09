from __future__ import annotations

from time import time
from typing import Dict, List

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response

from .api.v1.router import router as v1_router
from .core.config import get_settings
from .core.logging import configure_logging

settings = get_settings()
RATE_LIMIT_WINDOW_SECONDS = settings.rate_limit_window_seconds
RATE_LIMIT_MAX_REQUESTS = settings.rate_limit_max_requests
configure_logging()

app = FastAPI(title="Teeka Yatra API", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

_rate_limit_buckets: Dict[str, List[float]] = {}


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    if request.url.path in {"/health", "/api/v1/health"}:
        return await call_next(request)
    client = request.client.host if request.client is not None else "unknown"
    key = "%s:%s" % (client, request.url.path)
    now = time()
    bucket = [
        stamp
        for stamp in _rate_limit_buckets.get(key, [])
        if now - stamp < RATE_LIMIT_WINDOW_SECONDS
    ]
    if len(bucket) >= RATE_LIMIT_MAX_REQUESTS:
        return Response(content='{"detail":"Rate limit exceeded"}', status_code=429, media_type="application/json")
    bucket.append(now)
    _rate_limit_buckets[key] = bucket
    return await call_next(request)


app.include_router(v1_router, prefix="/api/v1")
app.include_router(v1_router)
