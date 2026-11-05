"""Prometheus metrics shared by all services (the Prometheus `job` label identifies the service)."""

from fastapi import APIRouter, Response
from prometheus_client import CONTENT_TYPE_LATEST, Counter, Histogram, generate_latest

HTTP_REQUESTS = Counter(
    "http_requests_total", "HTTP requests processed", ["method", "path", "status"]
)
HTTP_LATENCY = Histogram(
    "http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
    buckets=(0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0),
)
EVENTS_PUBLISHED = Counter("events_published_total", "Domain events published to the broker", ["event_type"])
EVENTS_CONSUMED = Counter("events_consumed_total", "Domain events consumed from the broker", ["event_type", "result"])
UPSTREAM_REQUESTS = Counter(
    "upstream_requests_total", "Calls to other services", ["upstream", "outcome"]
)


def metrics_router() -> APIRouter:
    router = APIRouter()

    @router.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(generate_latest(), media_type=CONTENT_TYPE_LATEST)

    return router
