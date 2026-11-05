from collections.abc import Callable
from contextlib import AbstractAsyncContextManager
from typing import Any

from fastapi import FastAPI

from .errors import register_exception_handlers
from .health import ReadinessCheck, health_router
from .metrics import metrics_router
from .middleware import RequestContextMiddleware


def create_base_app(
    *,
    service_name: str,
    title: str,
    description: str,
    version: str,
    lifespan: Callable[[FastAPI], AbstractAsyncContextManager[Any]] | None,
    readiness_checks: dict[str, ReadinessCheck],
    openapi_tags: list[dict[str, str]] | None = None,
    **fastapi_kwargs: Any,
) -> FastAPI:
    """FastAPI app with everything every service must have: error handling, request-id,
    structured access log, Prometheus metrics, /health and /ready, OpenAPI docs."""
    app = FastAPI(
        title=title,
        description=description,
        version=version,
        lifespan=lifespan,
        openapi_tags=openapi_tags,
        **fastapi_kwargs,
    )
    register_exception_handlers(app)
    app.add_middleware(RequestContextMiddleware)
    app.include_router(health_router(service_name, version, readiness_checks))
    app.include_router(metrics_router())
    return app
