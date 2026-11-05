"""Unified error model. Clients always receive the same JSON shape and never a stack trace:

    {"error": {"code": "not_found", "message": "Booking not found", "request_id": "...", "details": ...}}
"""

import logging
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.exc import SQLAlchemyError
from starlette.exceptions import HTTPException as StarletteHTTPException

from .log import request_id_ctx

logger = logging.getLogger("common.errors")


class AppError(Exception):
    status_code: int = 400
    code: str = "bad_request"
    default_message: str = "Bad request"

    def __init__(
        self,
        message: str | None = None,
        *,
        code: str | None = None,
        status_code: int | None = None,
        details: Any = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        self.message = message or self.default_message
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code
        self.details = details
        self.headers = headers
        super().__init__(self.message)


class BadRequestError(AppError):
    pass


class UnauthorizedError(AppError):
    status_code = 401
    code = "unauthorized"
    default_message = "Authentication required"


class ForbiddenError(AppError):
    status_code = 403
    code = "forbidden"
    default_message = "Insufficient permissions"


class NotFoundError(AppError):
    status_code = 404
    code = "not_found"
    default_message = "Resource not found"


class ConflictError(AppError):
    status_code = 409
    code = "conflict"
    default_message = "Conflict"


class RateLimitError(AppError):
    status_code = 429
    code = "rate_limited"
    default_message = "Too many requests"


class UpstreamError(AppError):
    status_code = 502
    code = "upstream_error"
    default_message = "Upstream service returned an error"


class ServiceUnavailableError(AppError):
    status_code = 503
    code = "service_unavailable"
    default_message = "Service temporarily unavailable"


class UpstreamTimeoutError(AppError):
    status_code = 504
    code = "upstream_timeout"
    default_message = "Upstream service did not respond in time"


class ErrorBody(BaseModel):
    code: str
    message: str
    request_id: str
    details: Any | None = None


class ErrorResponse(BaseModel):
    """Error envelope returned by every endpoint of every service."""

    error: ErrorBody


def _responses(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse} for code in codes}


# Ready-made OpenAPI `responses=` dicts for routers.
PUBLIC_RESPONSES = _responses(422)
AUTH_RESPONSES = _responses(401, 403, 422)

_STATUS_CODES = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    405: "method_not_allowed",
    409: "conflict",
    413: "payload_too_large",
    415: "unsupported_media_type",
    429: "rate_limited",
}


def error_payload(code: str, message: str, details: Any = None) -> dict[str, Any]:
    body: dict[str, Any] = {"code": code, "message": message, "request_id": request_id_ctx.get()}
    if details is not None:
        body["details"] = details
    return {"error": body}


def error_response(
    status_code: int, code: str, message: str, details: Any = None, headers: dict[str, str] | None = None
) -> JSONResponse:
    return JSONResponse(status_code=status_code, content=error_payload(code, message, details), headers=headers)


def _validation_details(exc: RequestValidationError) -> list[dict[str, str]]:
    details = []
    for err in exc.errors():
        loc = [str(part) for part in err.get("loc", ()) if part not in ("body", "query", "path", "header")]
        details.append({"field": ".".join(loc) or "request", "message": str(err.get("msg")), "type": str(err.get("type"))})
    return details


def register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        level = logging.WARNING if exc.status_code >= 500 else logging.INFO
        logger.log(level, "Request failed: %s", exc.message, extra={"error_code": exc.code, "status": exc.status_code})
        return error_response(exc.status_code, exc.code, exc.message, exc.details, exc.headers)

    @app.exception_handler(RequestValidationError)
    async def handle_validation(_: Request, exc: RequestValidationError) -> JSONResponse:
        details = _validation_details(exc)
        logger.info("Validation failed", extra={"error_code": "validation_error", "details": details})
        return error_response(422, "validation_error", "Request data is invalid", details)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http(_: Request, exc: StarletteHTTPException) -> JSONResponse:
        code = _STATUS_CODES.get(exc.status_code, "http_error")
        message = exc.detail if isinstance(exc.detail, str) else code.replace("_", " ").capitalize()
        return error_response(exc.status_code, code, message, headers=getattr(exc, "headers", None))

    @app.exception_handler(SQLAlchemyError)
    async def handle_db(_: Request, exc: SQLAlchemyError) -> JSONResponse:
        logger.error("Database error: %s", type(exc).__name__, exc_info=exc)
        return error_response(503, "database_error", "Database is temporarily unavailable")
