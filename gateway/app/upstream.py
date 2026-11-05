import asyncio
import logging
from collections.abc import Mapping
from typing import Any

import httpx

from common.errors import ServiceUnavailableError, UpstreamTimeoutError
from common.log import REQUEST_ID_HEADER, request_id_ctx
from common.metrics import UPSTREAM_REQUESTS
from common.resilience import CircuitBreaker

logger = logging.getLogger(__name__)

IDEMPOTENT_METHODS = {"GET", "HEAD", "OPTIONS", "PUT", "DELETE"}
RETRYABLE_STATUSES = {502, 503, 504}


class Upstream:
    """HTTP client for one backend service: timeouts, retries (idempotent methods only),
    circuit breaker and request-id propagation."""

    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        timeout: float,
        retries: int,
        breaker: CircuitBreaker,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.name = name
        self.retries = retries
        self.breaker = breaker
        self.client = httpx.AsyncClient(
            base_url=base_url, timeout=httpx.Timeout(timeout, connect=min(2.0, timeout)), transport=transport
        )

    async def request(
        self,
        method: str,
        path: str,
        *,
        params: Any = None,
        headers: Mapping[str, str] | None = None,
        content: bytes | None = None,
    ) -> httpx.Response:
        if not self.breaker.allow_request():
            UPSTREAM_REQUESTS.labels(self.name, "circuit_open").inc()
            raise ServiceUnavailableError(f"{self.name} service is temporarily unavailable", code="circuit_open")

        out_headers = dict(headers or {})
        out_headers[REQUEST_ID_HEADER] = request_id_ctx.get()
        attempts = 1 + (self.retries if method.upper() in IDEMPOTENT_METHODS else 0)
        error: Exception | None = None

        for attempt in range(1, attempts + 1):
            try:
                response = await self.client.request(method, path, params=params, headers=out_headers, content=content)
            except httpx.TimeoutException:
                self.breaker.record_failure()
                UPSTREAM_REQUESTS.labels(self.name, "timeout").inc()
                error = UpstreamTimeoutError(f"{self.name} service did not respond in time")
            except httpx.TransportError as exc:
                self.breaker.record_failure()
                UPSTREAM_REQUESTS.labels(self.name, "unavailable").inc()
                error = ServiceUnavailableError(f"{self.name} service is unavailable")
                logger.warning("Upstream transport error", extra={"upstream": self.name, "error": repr(exc)})
            else:
                if response.status_code >= 500:
                    self.breaker.record_failure()
                    UPSTREAM_REQUESTS.labels(self.name, "server_error").inc()
                    if response.status_code in RETRYABLE_STATUSES and attempt < attempts:
                        await asyncio.sleep(0.1 * 2**attempt)
                        continue
                else:
                    self.breaker.record_success()
                    UPSTREAM_REQUESTS.labels(self.name, "ok").inc()
                return response

            if attempt < attempts:
                logger.info("Retrying upstream call", extra={"upstream": self.name, "attempt": attempt})
                await asyncio.sleep(0.1 * 2**attempt)

        assert error is not None
        raise error

    async def close(self) -> None:
        await self.client.aclose()
