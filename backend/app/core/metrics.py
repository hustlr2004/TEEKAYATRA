from __future__ import annotations

from prometheus_client import CONTENT_TYPE_LATEST, CollectorRegistry, Counter, Gauge, Histogram, generate_latest


registry = CollectorRegistry()

request_latency_seconds = Histogram(
    "teeka_request_latency_seconds",
    "HTTP request latency in seconds.",
    ("method", "path", "status_code"),
    registry=registry,
)
request_errors_total = Counter(
    "teeka_request_errors_total",
    "HTTP requests that returned an error status.",
    ("method", "path", "status_code"),
    registry=registry,
)
doses_recorded_total = Counter(
    "teeka_doses_recorded_total",
    "Accepted dose records.",
    registry=registry,
)
sync_failures_total = Counter(
    "teeka_sync_failures_total",
    "Rejected or conflicted sync items.",
    ("reason",),
    registry=registry,
)
job_queue_length = Gauge(
    "teeka_job_queue_length",
    "Background jobs currently running or queued.",
    registry=registry,
)


def render_metrics() -> tuple[bytes, str]:
    return generate_latest(registry), CONTENT_TYPE_LATEST
