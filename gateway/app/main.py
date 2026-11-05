import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from common.app import create_base_app
from common.log import setup_logging
from common.resilience import CircuitBreaker
from common.security import JWTVerifier

from .config import Settings
from .docs import router as docs_router
from .proxy import router as proxy_router
from .ratelimit import RateLimiter, RedisRateLimiter
from .upstream import Upstream

logger = logging.getLogger(__name__)

DESCRIPTION = """
**API Gateway** — единая точка входа для клиентов.

* маршрутизация `/api/*` во внутренние сервисы;
* аутентификация (проверка JWT по JWKS auth-service) и грубая авторизация по ролям;
* rate limiting (Redis, fixed window);
* таймауты, retry идемпотентных запросов, circuit breaker на каждый сервис;
* агрегация: `GET /api/dashboard`, `GET /api/status`;
* сводная Swagger-документация всех сервисов на `/docs`.
"""


def create_app(
    settings: Settings | None = None,
    *,
    transport: httpx.AsyncBaseTransport | None = None,
    rate_limiter: RateLimiter | None = None,
    verifier: JWTVerifier | None = None,
) -> FastAPI:
    settings = settings or Settings()
    setup_logging(settings.service_name, settings.log_level)

    upstreams = {
        name: Upstream(
            name,
            url,
            timeout=settings.upstream_timeout_seconds,
            retries=settings.upstream_retries,
            breaker=CircuitBreaker(name, settings.circuit_failure_threshold, settings.circuit_reset_seconds),
            transport=transport,
        )
        for name, url in settings.upstream_urls.items()
    }
    limiter = rate_limiter or RedisRateLimiter(settings.redis_url)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        logger.info("Gateway started", extra={"upstreams": settings.upstream_urls})
        yield
        for upstream in upstreams.values():
            await upstream.close()
        await limiter.close()

    app = create_base_app(
        service_name=settings.service_name,
        title="Ticketing API Gateway",
        description=DESCRIPTION,
        version=settings.service_version,
        lifespan=lifespan,
        readiness_checks={"redis": limiter.ping},
        docs_url=None,
        redoc_url=None,
    )
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID", "X-RateLimit-Limit", "X-RateLimit-Remaining", "Retry-After"],
    )
    app.state.settings = settings
    app.state.upstreams = upstreams
    app.state.rate_limiter = limiter
    app.state.verifier = verifier or JWTVerifier(settings.effective_jwks_url)

    app.include_router(docs_router)
    app.include_router(proxy_router)
    return app
