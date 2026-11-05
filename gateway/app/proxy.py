import asyncio
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from pydantic import BaseModel

from common.errors import AUTH_RESPONSES, AppError, NotFoundError, RateLimitError, UnauthorizedError
from common.security import Principal, get_current_user

from .policy import LOGIN_PATHS, check_access, is_public, resolve_upstream
from .ratelimit import RateLimitResult
from .upstream import Upstream

logger = logging.getLogger(__name__)

router = APIRouter()

FORWARDED_REQUEST_HEADERS = {"authorization", "content-type", "accept", "accept-language", "idempotency-key", "user-agent"}
DROPPED_RESPONSE_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization", "te", "trailers",
    "transfer-encoding", "upgrade", "content-length", "content-encoding", "x-request-id", "server", "date",
}


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


async def authenticate(request: Request, required: bool) -> Principal | None:
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        if required:
            raise UnauthorizedError("Missing bearer token")
        return None
    try:
        return await request.app.state.verifier.verify(header[7:].strip())
    except UnauthorizedError:
        if required:
            raise
        return None  # public route: an invalid token simply means "anonymous"


async def enforce_rate_limit(request: Request, principal: Principal | None, path: str) -> RateLimitResult:
    settings = request.app.state.settings
    limiter = request.app.state.rate_limiter
    ip = client_ip(request)
    if request.method == "POST" and path in LOGIN_PATHS:
        result = await limiter.hit(f"login:{ip}", settings.login_rate_limit_per_minute)
    else:
        key = f"user:{principal.user_id}" if principal else f"ip:{ip}"
        result = await limiter.hit(key, settings.rate_limit_per_minute)
    if not result.allowed:
        logger.warning("Rate limit exceeded", extra={"path": path, "client_ip": ip})
        raise RateLimitError(
            "Rate limit exceeded, try again later",
            headers={**result.headers(), "Retry-After": str(result.reset_seconds)},
        )
    return result


class DashboardResponse(BaseModel):
    user_id: str
    profile: dict[str, Any] | None
    recent_bookings: list[dict[str, Any]] | None
    unread_notifications: int | None
    degraded: list[str]


@router.get(
    "/api/dashboard",
    response_model=DashboardResponse,
    tags=["aggregation"],
    summary="Aggregated view: profile + recent bookings + unread notifications",
    description="Calls user-, booking- and notification-service in parallel. If one of them fails the "
    "response is still returned and the failed part is listed in `degraded`.",
    responses=AUTH_RESPONSES,
)
async def dashboard(request: Request, principal: Principal = Depends(get_current_user)) -> DashboardResponse:
    await enforce_rate_limit(request, principal, "/api/dashboard")
    upstreams: dict[str, Upstream] = request.app.state.upstreams
    headers = {"authorization": request.headers["authorization"]}
    degraded: list[str] = []

    async def fetch(name: str, path: str, params: dict | None = None) -> Any:
        try:
            response = await upstreams[name].request("GET", path, headers=headers, params=params)
            if response.status_code == 200:
                return response.json()
            logger.warning("Dashboard part failed", extra={"upstream": name, "status": response.status_code})
        except AppError as exc:
            logger.warning("Dashboard part unavailable", extra={"upstream": name, "error": exc.message})
        degraded.append(name)
        return None

    profile, bookings, unread = await asyncio.gather(
        fetch("user", "/api/users/me"),
        fetch("booking", "/api/bookings", {"limit": 5}),
        fetch("notification", "/api/notifications/unread-count"),
    )
    return DashboardResponse(
        user_id=str(principal.user_id),
        profile=profile,
        recent_bookings=bookings["items"] if bookings else None,
        unread_notifications=unread["count"] if unread else None,
        degraded=sorted(degraded),
    )


class ServiceStatus(BaseModel):
    status: str
    latency_ms: float | None
    circuit: str


class SystemStatus(BaseModel):
    gateway: str
    services: dict[str, ServiceStatus]


@router.get("/api/status", response_model=SystemStatus, tags=["aggregation"], summary="Health of all backend services")
async def system_status(request: Request) -> SystemStatus:
    upstreams: dict[str, Upstream] = request.app.state.upstreams

    async def probe(name: str, upstream: Upstream) -> tuple[str, ServiceStatus]:
        started = time.perf_counter()
        try:
            response = await upstream.request("GET", "/ready")
            state = "up" if response.status_code == 200 else "degraded"
        except AppError:
            state = "down"
        latency = round((time.perf_counter() - started) * 1000, 1)
        return name, ServiceStatus(status=state, latency_ms=latency, circuit=upstream.breaker.state)

    results = dict(await asyncio.gather(*(probe(n, u) for n, u in upstreams.items())))
    return SystemStatus(gateway="up", services=results)


@router.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"], include_in_schema=False)
async def proxy(request: Request, path: str) -> Response:
    full_path = f"/api/{path}"
    upstream_name = resolve_upstream(full_path)
    if upstream_name is None:
        raise NotFoundError("Route not found")

    principal = await authenticate(request, required=not is_public(request.method, full_path))
    limit = await enforce_rate_limit(request, principal, full_path)
    check_access(request.method, full_path, principal)

    headers = {k: v for k, v in request.headers.items() if k.lower() in FORWARDED_REQUEST_HEADERS}
    headers["X-Forwarded-For"] = client_ip(request)
    if principal is not None:
        headers["X-User-Id"] = str(principal.user_id)
        headers["X-User-Role"] = principal.role

    upstream: Upstream = request.app.state.upstreams[upstream_name]
    response = await upstream.request(
        request.method, full_path, params=request.query_params.multi_items(), headers=headers, content=await request.body()
    )
    out_headers = {k: v for k, v in response.headers.items() if k.lower() not in DROPPED_RESPONSE_HEADERS}
    out_headers.update(limit.headers())
    return Response(content=response.content, status_code=response.status_code, headers=out_headers)
