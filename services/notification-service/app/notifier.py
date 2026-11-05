import logging
import uuid
from typing import Any

from common.db import utcnow
from common.messaging import EventEnvelope, EventRouter

from .repository import NotificationRepository

logger = logging.getLogger(__name__)


class EmailSender:
    """Email channel stub: in this lab the "sending" is a structured log line."""

    async def send(self, to: str | None, subject: str, body: str) -> None:
        logger.info("Email sent", extra={"to": to, "subject": subject})


def _render(event: EventEnvelope) -> tuple[str, str] | None:
    p = event.payload
    title = p.get("event_title", "")
    qty = p.get("quantity")
    amount = f"{p.get('amount', '')} {p.get('currency', '')}".strip()
    templates = {
        "user.registered": ("Добро пожаловать!", f"{p.get('full_name', '')}, ваш аккаунт создан. Приятных мероприятий!"),
        "booking.created": ("Бронь создана", f"Бронь на «{title}» ({qty} шт.) ожидает оплаты: {amount}."),
        "booking.confirmed": ("Бронь подтверждена", f"Оплата прошла. Ваши билеты на «{title}» ({qty} шт.) подтверждены."),
        "booking.cancelled": ("Бронь отменена", f"Бронь на «{title}» отменена. Причина: {p.get('reason', '—')}."),
        "payment.failed": ("Платёж отклонён", f"Не удалось списать {amount}. Причина: {p.get('reason', '—')}."),
        "payment.refunded": ("Возврат средств", f"Мы вернули {amount} на вашу карту."),
    }
    return templates.get(event.event_type)


class Notifier:
    def __init__(self, repo: NotificationRepository, sender: EmailSender) -> None:
        self.repo = repo
        self.sender = sender

    async def handle(self, event: EventEnvelope) -> None:
        payload = event.payload
        user_id = str(payload["user_id"])

        if event.event_type == "user.registered":
            await self.repo.upsert_contact(user_id, payload["email"], payload.get("full_name", ""))

        rendered = _render(event)
        if rendered is None:
            return
        subject, body = rendered

        contact = await self.repo.get_contact(user_id)
        recipient = payload.get("user_email") or payload.get("email") or (contact or {}).get("email")

        notification: dict[str, Any] = {
            "_id": str(uuid.uuid4()),
            "event_id": event.event_id,  # unique index -> each event produces at most one notification
            "event_type": event.event_type,
            "user_id": user_id,
            "channel": "email",
            "recipient": recipient,
            "title": subject,
            "message": body,
            "status": "pending",
            "read": False,
            "created_at": utcnow(),
        }
        if not await self.repo.insert(notification):
            existing = await self.repo.get_by_event(event.event_id)
            if existing is None or existing.get("status") == "sent":
                logger.info("Duplicate event, notification already sent", extra={"event_id": event.event_id})
                return
            notification = existing  # stored earlier but sending failed -> retry sending

        await self.sender.send(recipient, subject, body)
        await self.repo.mark_sent(notification["_id"], utcnow())
        logger.info("Notification delivered", extra={"event_type": event.event_type, "user_id": user_id})


ROUTING_KEYS = [
    "user.registered",
    "booking.created",
    "booking.confirmed",
    "booking.cancelled",
    "payment.failed",
    "payment.refunded",
]


def build_event_router(notifier: Notifier) -> EventRouter:
    router = EventRouter()
    for key in ROUTING_KEYS:
        router.on(key, notifier.handle)
    return router
