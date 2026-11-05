import asyncio
import logging
from collections.abc import Awaitable, Callable
from typing import Any

from fastapi import APIRouter
from fastapi.responses import JSONResponse
from pydantic import BaseModel

logger = logging.getLogger("common.health")

ReadinessCheck = Callable[[], Awaitable[Any]]


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class ReadinessResponse(BaseModel):
    status: str
    service: str
    checks: dict[str, str]


def health_router(service: str, version: str, checks: dict[str, ReadinessCheck], timeout: float = 2.0) -> APIRouter:
    """`/health` = liveness (process is up); `/ready` = readiness (all dependencies reachable)."""

    router = APIRouter(tags=["health"])

    @router.get("/health", response_model=HealthResponse, summary="Liveness probe")
    async def health() -> HealthResponse:
        return HealthResponse(status="ok", service=service, version=version)

    @router.get(
        "/ready",
        response_model=ReadinessResponse,
        summary="Readiness probe (checks DB / broker / cache)",
        responses={503: {"model": ReadinessResponse}},
    )
    async def ready() -> JSONResponse:
        async def run(name: str, check: ReadinessCheck) -> tuple[str, str]:
            try:
                await asyncio.wait_for(check(), timeout=timeout)
                return name, "ok"
            except Exception as exc:  # noqa: BLE001 - any failure means "not ready"
                logger.warning("Readiness check failed", extra={"check": name, "error": repr(exc)})
                return name, f"error: {type(exc).__name__}"

        results = dict(await asyncio.gather(*(run(n, c) for n, c in checks.items())))
        ok = all(v == "ok" for v in results.values())
        body = ReadinessResponse(status="ready" if ok else "not_ready", service=service, checks=results)
        return JSONResponse(status_code=200 if ok else 503, content=body.model_dump())

    return router
