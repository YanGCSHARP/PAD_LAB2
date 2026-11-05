"""RabbitMQ event bus (aio-pika).

Topology:
  * topic exchange `ticketing.events` — routing key == event type (e.g. `booking.created`);
  * every consumer service owns a durable queue `<service>.events` bound to the keys it needs;
  * failed messages are retried with back-off (re-published with `x-retry-count`), and after
    `max_retries` they are dead-lettered to `<queue>.dlq` through the `ticketing.dlx` exchange.
"""

import asyncio
import json
import logging
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from datetime import datetime
from functools import partial
from typing import Any

import aio_pika
from aio_pika.abc import AbstractChannel, AbstractIncomingMessage, AbstractRobustConnection

from .db import utcnow
from .log import request_id_ctx
from .metrics import EVENTS_CONSUMED, EVENTS_PUBLISHED

logger = logging.getLogger("common.messaging")

EXCHANGE = "ticketing.events"
DEAD_LETTER_EXCHANGE = "ticketing.dlx"


@dataclass
class EventEnvelope:
    event_id: str
    event_type: str
    occurred_at: str
    producer: str
    payload: dict[str, Any] = field(default_factory=dict)

    @classmethod
    def parse(cls, raw: bytes) -> "EventEnvelope":
        data = json.loads(raw)
        return cls(
            event_id=str(data["event_id"]),
            event_type=str(data["event_type"]),
            occurred_at=str(data.get("occurred_at", "")),
            producer=str(data.get("producer", "unknown")),
            payload=dict(data.get("payload") or {}),
        )


EventHandler = Callable[[EventEnvelope], Awaitable[None]]


class EventBus:
    def __init__(self, url: str, service: str, *, max_retries: int = 5) -> None:
        self.url = url
        self.service = service
        self.max_retries = max_retries
        self._connection: AbstractRobustConnection | None = None
        self._channel: AbstractChannel | None = None
        self._exchange: aio_pika.abc.AbstractExchange | None = None

    @property
    def is_connected(self) -> bool:
        return self._connection is not None and not self._connection.is_closed

    async def connect(self, attempts: int = 30, delay: float = 2.0) -> None:
        for attempt in range(1, attempts + 1):
            try:
                self._connection = await aio_pika.connect_robust(self.url, timeout=10, client_properties={"connection_name": self.service})
                break
            except Exception as exc:  # noqa: BLE001
                logger.warning("RabbitMQ not reachable yet", extra={"attempt": attempt, "error": repr(exc)})
                if attempt == attempts:
                    raise
                await asyncio.sleep(delay)
        assert self._connection is not None
        self._channel = await self._connection.channel(publisher_confirms=True)
        self._exchange = await self._channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        await self._channel.declare_exchange(DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)
        logger.info("Connected to RabbitMQ")

    async def ping(self) -> None:
        if not self.is_connected:
            raise ConnectionError("RabbitMQ connection is closed")

    async def close(self) -> None:
        if self._connection is not None:
            await self._connection.close()

    async def publish(
        self,
        event_type: str,
        payload: dict[str, Any],
        *,
        event_id: str | None = None,
        request_id: str | None = None,
        occurred_at: datetime | None = None,
    ) -> None:
        if self._exchange is None:
            raise ConnectionError("Event bus is not connected")
        event_id = event_id or str(uuid.uuid4())
        envelope = {
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": (occurred_at or utcnow()).isoformat(),
            "producer": self.service,
            "payload": payload,
        }
        message = aio_pika.Message(
            body=json.dumps(envelope, default=str).encode(),
            content_type="application/json",
            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
            message_id=event_id,
            type=event_type,
            headers={"x-request-id": request_id or request_id_ctx.get()},
        )
        await self._exchange.publish(message, routing_key=event_type)
        EVENTS_PUBLISHED.labels(event_type).inc()
        logger.info("Event published", extra={"event_type": event_type, "event_id": event_id})

    async def subscribe(self, queue_name: str, routing_keys: list[str], handler: EventHandler, prefetch: int = 10) -> None:
        if self._connection is None:
            raise ConnectionError("Event bus is not connected")
        channel = await self._connection.channel()
        await channel.set_qos(prefetch_count=prefetch)
        exchange = await channel.declare_exchange(EXCHANGE, aio_pika.ExchangeType.TOPIC, durable=True)
        dlx = await channel.declare_exchange(DEAD_LETTER_EXCHANGE, aio_pika.ExchangeType.DIRECT, durable=True)

        dlq = await channel.declare_queue(f"{queue_name}.dlq", durable=True)
        await dlq.bind(dlx, routing_key=queue_name)

        queue = await channel.declare_queue(
            queue_name,
            durable=True,
            arguments={"x-dead-letter-exchange": DEAD_LETTER_EXCHANGE, "x-dead-letter-routing-key": queue_name},
        )
        for key in routing_keys:
            await queue.bind(exchange, routing_key=key)
        await queue.consume(partial(self._on_message, channel, queue_name, handler))
        logger.info("Subscribed to events", extra={"queue": queue_name, "routing_keys": routing_keys})

    async def _on_message(
        self, channel: AbstractChannel, queue_name: str, handler: EventHandler, message: AbstractIncomingMessage
    ) -> None:
        headers = dict(message.headers or {})
        token = request_id_ctx.set(str(headers.get("x-request-id") or uuid.uuid4().hex))
        retries = int(headers.get("x-retry-count", 0) or 0)
        try:
            try:
                envelope = EventEnvelope.parse(message.body)
            except (ValueError, KeyError, TypeError):
                logger.error("Malformed message moved to DLQ", extra={"queue": queue_name})
                EVENTS_CONSUMED.labels("unknown", "malformed").inc()
                await message.reject(requeue=False)
                return

            log_extra = {"event_type": envelope.event_type, "event_id": envelope.event_id, "retry": retries}
            try:
                await handler(envelope)
            except Exception as exc:  # noqa: BLE001
                EVENTS_CONSUMED.labels(envelope.event_type, "error").inc()
                if retries < self.max_retries:
                    delay = min(0.5 * 2**retries, 10.0)
                    logger.warning("Event handling failed, retry scheduled", extra={**log_extra, "error": repr(exc), "delay_s": delay})
                    await asyncio.sleep(delay)
                    await channel.default_exchange.publish(
                        aio_pika.Message(
                            body=message.body,
                            content_type=message.content_type,
                            delivery_mode=aio_pika.DeliveryMode.PERSISTENT,
                            message_id=message.message_id,
                            type=message.type,
                            headers={**headers, "x-retry-count": retries + 1},
                        ),
                        routing_key=queue_name,
                    )
                    await message.ack()
                else:
                    logger.error("Event handling failed permanently, moved to DLQ", extra=log_extra, exc_info=exc)
                    await message.reject(requeue=False)
                return

            await message.ack()
            EVENTS_CONSUMED.labels(envelope.event_type, "ok").inc()
            logger.info("Event processed", extra=log_extra)
        finally:
            request_id_ctx.reset(token)


class EventRouter:
    """Dispatches an envelope to the handler registered for its event type."""

    def __init__(self) -> None:
        self._handlers: dict[str, EventHandler] = {}

    def on(self, event_type: str, handler: EventHandler) -> None:
        self._handlers[event_type] = handler

    @property
    def routing_keys(self) -> list[str]:
        return list(self._handlers)

    async def __call__(self, envelope: EventEnvelope) -> None:
        handler = self._handlers.get(envelope.event_type)
        if handler is None:
            logger.info("No handler for event, skipping", extra={"event_type": envelope.event_type})
            return
        await handler(envelope)
