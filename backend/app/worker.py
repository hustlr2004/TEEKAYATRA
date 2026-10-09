from __future__ import annotations

import asyncio
import json
from datetime import date, datetime
from typing import Any, Callable, Dict

from arq.connections import RedisSettings
from arq.cron import cron
from sqlalchemy import delete, select

from .core.config import get_settings
from .database import SessionLocal
from .models import DeadLetterLog, ExternalRegisterRow, JobRun, JobStatus
from .services.analytics import manager_dashboard, parse_external_register_csv, simulated_external_register_csv
from .services.cache import LEADERBOARD_CACHE_KEY, MANAGER_DASHBOARD_CACHE_KEY, invalidate_analytics_cache, set_json
from .services.gamification import village_leaderboard
from .services.notifications import schedule_reminders
from .services.responsible_design import run_retention_job

JobHandler = Callable[[Any, Dict[str, Any]], Dict[str, Any]]


async def schedule_and_send_reminders(ctx: dict[str, Any], today: str | None = None) -> dict[str, Any]:
    return await _run_job("schedule_and_send_reminders", {"today": today}, _schedule_and_send_reminders)


async def nightly_analytics_aggregation(ctx: dict[str, Any], today: str | None = None) -> dict[str, Any]:
    return await _run_job("nightly_analytics_aggregation", {"today": today}, _nightly_analytics_aggregation)


async def leaderboard_recompute(ctx: dict[str, Any]) -> dict[str, Any]:
    return await _run_job("leaderboard_recompute", {}, _leaderboard_recompute)


async def data_retention_cleanup(ctx: dict[str, Any], today: str | None = None) -> dict[str, Any]:
    return await _run_job("data_retention_cleanup", {"today": today}, _data_retention_cleanup)


async def import_external_register_csv(ctx: dict[str, Any], csv_text: str, source_name: str = "external") -> dict[str, Any]:
    return await _run_job(
        "import_external_register_csv",
        {"source_name": source_name, "csv_text": csv_text},
        _import_external_register_csv,
    )


async def _run_job(job_name: str, payload: Dict[str, Any], handler: JobHandler) -> dict[str, Any]:
    settings = get_settings()
    last_error: Exception | None = None
    for attempt in range(1, settings.job_max_retries + 1):
        async with SessionLocal() as db:
            job_run = JobRun(job_name=job_name, status=JobStatus.running, attempts=attempt, payload=json.dumps(payload), result="{}")
            db.add(job_run)
            await db.commit()
            await db.refresh(job_run)
            try:
                result = await db.run_sync(lambda sync_db: handler(sync_db, payload))
                job_run.status = JobStatus.succeeded
                job_run.result = json.dumps(result, default=str)
                job_run.finished_at = datetime.utcnow()
                await db.commit()
                return result
            except Exception as exc:
                last_error = exc
                job_run.status = JobStatus.failed
                job_run.error = str(exc)
                job_run.finished_at = datetime.utcnow()
                await db.commit()
        if attempt < settings.job_max_retries:
            await asyncio.sleep(2 ** (attempt - 1))

    async with SessionLocal() as db:
        db.add(
            DeadLetterLog(
                job_name=job_name,
                payload=json.dumps(payload),
                error=str(last_error) if last_error is not None else "unknown error",
                attempts=settings.job_max_retries,
            )
        )
        await db.commit()
    raise RuntimeError("%s failed after %s attempts: %s" % (job_name, settings.job_max_retries, last_error))


def _schedule_and_send_reminders(db, payload: Dict[str, Any]) -> dict[str, Any]:
    today = _payload_date(payload)
    logs = schedule_reminders(db, today)
    return {"sent": len(logs)}


def _nightly_analytics_aggregation(db, payload: Dict[str, Any]) -> dict[str, Any]:
    today = _payload_date(payload)
    dashboard = manager_dashboard(db, today, simulated_external_register_csv())
    set_json(MANAGER_DASHBOARD_CACHE_KEY, dashboard)
    return {"sections": sorted(dashboard.keys())}


def _leaderboard_recompute(db, payload: Dict[str, Any]) -> dict[str, Any]:
    rows = [row.__dict__ for row in village_leaderboard(db)]
    set_json(LEADERBOARD_CACHE_KEY, rows)
    return {"rows": len(rows)}


def _data_retention_cleanup(db, payload: Dict[str, Any]) -> dict[str, Any]:
    result = run_retention_job(db, _payload_date(payload))
    return result.__dict__


def _import_external_register_csv(db, payload: Dict[str, Any]) -> dict[str, Any]:
    source_name = str(payload.get("source_name") or "external")
    parsed = parse_external_register_csv(str(payload.get("csv_text") or ""))
    db.execute(delete(ExternalRegisterRow).where(ExternalRegisterRow.source_name == source_name))
    for (block, vaccine_code), count in parsed.items():
        db.add(ExternalRegisterRow(source_name=source_name, block=block, vaccine_code=vaccine_code, count=count))
    db.commit()
    invalidate_analytics_cache()
    return {"source_name": source_name, "rows": len(parsed)}


def _payload_date(payload: Dict[str, Any]) -> date:
    value = payload.get("today")
    return date.fromisoformat(value) if isinstance(value, str) and value else date.today()


def redis_settings() -> RedisSettings:
    settings = get_settings()
    return RedisSettings.from_dsn(settings.redis_url)


class WorkerSettings:
    functions = [
        schedule_and_send_reminders,
        nightly_analytics_aggregation,
        leaderboard_recompute,
        data_retention_cleanup,
        import_external_register_csv,
    ]
    cron_jobs = [
        cron(schedule_and_send_reminders, hour=7, minute=0),
        cron(nightly_analytics_aggregation, hour=1, minute=0),
        cron(leaderboard_recompute, hour=1, minute=20),
        cron(data_retention_cleanup, hour=2, minute=0),
    ]
    redis_settings = redis_settings()
