import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response
from starlette.routing import Match

from .errors import error_response
from .log import REQUEST_ID_HEADER, request_id_ctx
from .metrics import HTTP_LATENCY, HTTP_REQUESTS

logger = logging.getLogger("http")

_QUIET_PATHS = {"/health", "/ready", "/metrics"}


def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    if route is not None and getattr(route, "path", None):
        return route.path
    for candidate in request.app.router.routes:
        match, _ = candidate.matches(request.scope)
        if match == Match.FULL:
            return getattr(candidate, "path", "unmatched")
    return "unmatched"


class RequestContextMiddleware(BaseHTTPMiddleware):
    """Assigns/propagates X-Request-ID, writes the access log, records metrics and
    converts any unhandled exception into a sanitized 500 response."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        request_id = request.headers.get(REQUEST_ID_HEADER) or uuid.uuid4().hex
        token = request_id_ctx.set(request_id[:64])
        started = time.perf_counter()
        try:
            try:
                response = await call_next(request)
            except Exception:
                logger.exception("Unhandled error while processing request")
                response = error_response(500, "internal_error", "Internal server error")

            elapsed = time.perf_counter() - started
            path = _route_template(request)
            HTTP_REQUESTS.labels(request.method, path, str(response.status_code)).inc()
            HTTP_LATENCY.labels(request.method, path).observe(elapsed)

            response.headers[REQUEST_ID_HEADER] = request_id_ctx.get()
            if request.url.path not in _QUIET_PATHS:
                logger.info(
                    "%s %s -> %s",
                    request.method,
                    request.url.path,
                    response.status_code,
                    extra={
                        "method": request.method,
                        "path": request.url.path,
                        "status": response.status_code,
                        "duration_ms": round(elapsed * 1000, 2),
                        "client_ip": request.client.host if request.client else None,
                    },
                )
            return response
        finally:
            request_id_ctx.reset(token)
