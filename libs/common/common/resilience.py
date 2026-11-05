import logging
import time

logger = logging.getLogger("common.resilience")


class CircuitBreaker:
    """Minimal circuit breaker: closed -> open after N consecutive failures -> half-open after timeout."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(self, name: str, failure_threshold: int = 5, reset_timeout: float = 15.0) -> None:
        self.name = name
        self.failure_threshold = failure_threshold
        self.reset_timeout = reset_timeout
        self.state = self.CLOSED
        self.failures = 0
        self.opened_at = 0.0

    def allow_request(self) -> bool:
        if self.state == self.OPEN:
            if time.monotonic() - self.opened_at >= self.reset_timeout:
                self.state = self.HALF_OPEN
                logger.info("Circuit half-open, probing", extra={"circuit": self.name})
                return True
            return False
        return True

    def record_success(self) -> None:
        if self.state != self.CLOSED:
            logger.info("Circuit closed", extra={"circuit": self.name})
        self.state = self.CLOSED
        self.failures = 0

    def record_failure(self) -> None:
        self.failures += 1
        if self.state == self.HALF_OPEN or self.failures >= self.failure_threshold:
            if self.state != self.OPEN:
                logger.warning("Circuit opened", extra={"circuit": self.name, "failures": self.failures})
            self.state = self.OPEN
            self.opened_at = time.monotonic()
