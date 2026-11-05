"""Simulated external payment provider (PSP). Replace with a real SDK in production."""

import asyncio
import logging
import uuid
from dataclasses import dataclass
from decimal import Decimal

logger = logging.getLogger(__name__)


@dataclass
class ChargeResult:
    success: bool
    reference: str | None = None
    reason: str | None = None


class FakePaymentProvider:
    def __init__(self, latency_ms: int, decline_above: Decimal) -> None:
        self.latency = latency_ms / 1000
        self.decline_above = decline_above

    async def charge(self, amount: Decimal, currency: str, reference: str) -> ChargeResult:
        await asyncio.sleep(self.latency)
        if amount > self.decline_above:
            logger.info("Charge declined by provider", extra={"reference": reference, "amount": str(amount)})
            return ChargeResult(False, reason="insufficient_funds")
        return ChargeResult(True, reference=f"psp_{uuid.uuid4().hex[:16]}")

    async def refund(self, provider_reference: str, amount: Decimal) -> str:
        await asyncio.sleep(self.latency)
        return f"rfd_{uuid.uuid4().hex[:16]}"
