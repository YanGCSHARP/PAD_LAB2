"""Structured JSON logging with request-id correlation."""

import json
import logging
import sys
from contextvars import ContextVar
from datetime import UTC, datetime

REQUEST_ID_HEADER = "X-Request-ID"

request_id_ctx: ContextVar[str] = ContextVar("request_id", default="-")

_STANDARD_ATTRS = set(vars(logging.LogRecord("", 0, "", 0, "", (), None))) | {"message", "asctime", "taskName"}


class JsonFormatter(logging.Formatter):
    """Formats every record as one JSON line: timestamp, service, level, request_id, message + extras."""

    def __init__(self, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        entry: dict[str, object] = {
            "timestamp": datetime.fromtimestamp(record.created, UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z"),
            "service": self.service,
            "level": record.levelname,
            "request_id": request_id_ctx.get(),
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key not in _STANDARD_ATTRS and key not in entry and not key.startswith("_"):
                entry[key] = value
        if record.exc_info:
            entry["exception"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False, default=str)


def setup_logging(service: str, level: str = "INFO") -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter(service))

    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(level.upper())

    for name in ("uvicorn", "uvicorn.error"):
        uv_logger = logging.getLogger(name)
        uv_logger.handlers.clear()
        uv_logger.propagate = True
    logging.getLogger("uvicorn.access").disabled = True  # replaced by our access log middleware

    for noisy in ("aio_pika", "aiormq", "httpx", "httpcore", "pymongo", "asyncio"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
