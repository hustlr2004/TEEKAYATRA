from __future__ import annotations

from functools import lru_cache
from typing import List

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    database_url: str = "postgresql+asyncpg://teeka:teeka@postgres:5432/teeka_yatra"
    jwt_secret: str = "teeka-yatra-dev-secret-with-at-least-32-bytes"
    jwt_algorithm: str = "HS256"
    phone_encryption_key: str = ""
    allowed_origins: List[str] = Field(
        default_factory=lambda: [
            "http://localhost:5173",
            "http://127.0.0.1:5173",
            "https://localhost:5173",
            "https://127.0.0.1:5173",
        ]
    )
    default_demo_password: str = "demo123"
    rate_limit_window_seconds: int = 60
    rate_limit_max_requests: int = 120
    redis_url: str = "redis://redis:6379/0"
    cache_ttl_seconds: int = 300
    job_max_retries: int = 3

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    @field_validator("allowed_origins", mode="before")
    @classmethod
    def split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value


@lru_cache
def get_settings() -> Settings:
    return Settings()
