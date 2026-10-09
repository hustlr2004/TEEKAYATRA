from __future__ import annotations

import json
import logging

from fastapi.testclient import TestClient

from app import main
from app.core.logging import configure_logging, request_id_var


def test_http_errors_use_consistent_envelope() -> None:
    client = TestClient(main.app)

    response = client.get("/children/1", headers={"X-Request-ID": "req-test-1"})

    assert response.status_code == 401
    assert response.headers["X-Request-ID"] == "req-test-1"
    assert response.json() == {
        "code": "unauthorized",
        "message": "Missing bearer token",
        "details": {},
        "request_id": "req-test-1",
    }


def test_validation_errors_use_consistent_envelope() -> None:
    client = TestClient(main.app)

    response = client.post("/auth/login", json={"phone": "+910000000001"})

    assert response.status_code == 422
    body = response.json()
    assert body["code"] == "validation_error"
    assert body["message"] == "Request validation failed"
    assert body["request_id"]
    assert body["details"]["errors"][0]["type"]


def test_ready_reports_db_and_redis_checks(monkeypatch) -> None:
    async def ok_db() -> bool:
        return True

    monkeypatch.setattr(main, "_check_db", ok_db)
    monkeypatch.setattr(main, "_check_redis", lambda: True)
    client = TestClient(main.app)

    response = client.get("/ready")

    assert response.status_code == 200
    assert response.json() == {"status": "ok", "checks": {"db": True, "redis": True}}


def test_ready_returns_503_when_a_dependency_is_down(monkeypatch) -> None:
    async def ok_db() -> bool:
        return True

    monkeypatch.setattr(main, "_check_db", ok_db)
    monkeypatch.setattr(main, "_check_redis", lambda: False)
    client = TestClient(main.app)

    response = client.get("/ready")

    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"db": True, "redis": False}}


def test_metrics_endpoint_exposes_prometheus_text(monkeypatch) -> None:
    async def refresh() -> None:
        return None

    monkeypatch.setattr(main, "_refresh_job_queue_metric", refresh)
    client = TestClient(main.app)
    client.get("/health")

    response = client.get("/metrics")

    assert response.status_code == 200
    assert "teeka_request_latency_seconds" in response.text
    assert "teeka_request_errors_total" in response.text
    assert "teeka_doses_recorded_total" in response.text
    assert "teeka_sync_failures_total" in response.text
    assert "teeka_job_queue_length" in response.text


def test_json_logging_includes_request_id_without_personal_data(capfd) -> None:
    configure_logging()
    request_id_var.set("req-log-1")

    logging.getLogger("teeka.test").info("request completed", extra={"method": "GET", "path": "/health", "status_code": 200})
    captured = capfd.readouterr().err.strip()
    payload = json.loads(captured)

    assert payload["request_id"] == "req-log-1"
    assert payload["method"] == "GET"
    assert "authorization" not in payload
    assert "phone" not in payload
