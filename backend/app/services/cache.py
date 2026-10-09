from __future__ import annotations

import json
from typing import Any, Optional

import redis

from ..core.config import get_settings

LEADERBOARD_CACHE_KEY = "teeka:leaderboard:village"
MANAGER_DASHBOARD_CACHE_KEY = "teeka:analytics:manager"


def _client() -> redis.Redis:
    return redis.Redis.from_url(get_settings().redis_url, decode_responses=True)


def get_json(key: str) -> Optional[Any]:
    try:
        value = _client().get(key)
    except redis.RedisError:
        return None
    if value is None:
        return None
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return None


def set_json(key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
    ttl = ttl_seconds or get_settings().cache_ttl_seconds
    try:
        _client().setex(key, ttl, json.dumps(value, default=str))
    except (TypeError, redis.RedisError):
        return


def invalidate_analytics_cache() -> None:
    try:
        _client().delete(LEADERBOARD_CACHE_KEY, MANAGER_DASHBOARD_CACHE_KEY)
    except redis.RedisError:
        return
