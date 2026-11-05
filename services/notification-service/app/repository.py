"""Storage for notifications and the local projection of user contacts.

MongoDB fits here: notifications are append-mostly documents with a flexible shape (different
templates/channels), they are always read per user, and no cross-entity transactions are needed.
"""

from datetime import datetime
from typing import Any, Protocol

from pymongo import ASCENDING, DESCENDING, AsyncMongoClient
from pymongo.errors import DuplicateKeyError


class NotificationRepository(Protocol):
    async def upsert_contact(self, user_id: str, email: str, full_name: str) -> None: ...

    async def get_contact(self, user_id: str) -> dict[str, Any] | None: ...

    async def insert(self, notification: dict[str, Any]) -> bool: ...

    async def get_by_event(self, event_id: str) -> dict[str, Any] | None: ...

    async def mark_sent(self, notification_id: str, sent_at: datetime) -> None: ...

    async def list_for_user(self, user_id: str, unread_only: bool, limit: int, offset: int) -> tuple[list[dict], int]: ...

    async def mark_read(self, user_id: str, notification_id: str) -> bool: ...

    async def unread_count(self, user_id: str) -> int: ...

    async def ping(self) -> None: ...


class MongoNotificationRepository:
    def __init__(self, url: str, database: str) -> None:
        self.client: AsyncMongoClient = AsyncMongoClient(url, serverSelectionTimeoutMS=3000, uuidRepresentation="standard", tz_aware=True)
        self.db = self.client[database]
        self.notifications = self.db["notifications"]
        self.contacts = self.db["contacts"]

    async def init(self) -> None:
        await self.notifications.create_index([("event_id", ASCENDING)], unique=True)  # idempotency
        await self.notifications.create_index([("user_id", ASCENDING), ("created_at", DESCENDING)])
        await self.notifications.create_index([("user_id", ASCENDING), ("read", ASCENDING)])

    async def upsert_contact(self, user_id: str, email: str, full_name: str) -> None:
        await self.contacts.update_one({"_id": user_id}, {"$set": {"email": email, "full_name": full_name}}, upsert=True)

    async def get_contact(self, user_id: str) -> dict[str, Any] | None:
        return await self.contacts.find_one({"_id": user_id})

    async def insert(self, notification: dict[str, Any]) -> bool:
        try:
            await self.notifications.insert_one(notification)
            return True
        except DuplicateKeyError:
            return False

    async def get_by_event(self, event_id: str) -> dict[str, Any] | None:
        return await self.notifications.find_one({"event_id": event_id})

    async def mark_sent(self, notification_id: str, sent_at: datetime) -> None:
        await self.notifications.update_one({"_id": notification_id}, {"$set": {"status": "sent", "sent_at": sent_at}})

    async def list_for_user(self, user_id: str, unread_only: bool, limit: int, offset: int) -> tuple[list[dict], int]:
        query: dict[str, Any] = {"user_id": user_id}
        if unread_only:
            query["read"] = False
        total = await self.notifications.count_documents(query)
        cursor = self.notifications.find(query).sort("created_at", DESCENDING).skip(offset).limit(limit)
        return [doc async for doc in cursor], total

    async def mark_read(self, user_id: str, notification_id: str) -> bool:
        result = await self.notifications.update_one({"_id": notification_id, "user_id": user_id}, {"$set": {"read": True}})
        return result.matched_count == 1

    async def unread_count(self, user_id: str) -> int:
        return await self.notifications.count_documents({"user_id": user_id, "read": False})

    async def ping(self) -> None:
        await self.db.command("ping")

    async def close(self) -> None:
        await self.client.close()


class InMemoryNotificationRepository:
    """Used by unit tests."""

    def __init__(self) -> None:
        self.contacts: dict[str, dict] = {}
        self.items: dict[str, dict] = {}

    async def upsert_contact(self, user_id: str, email: str, full_name: str) -> None:
        self.contacts[user_id] = {"_id": user_id, "email": email, "full_name": full_name}

    async def get_contact(self, user_id: str) -> dict[str, Any] | None:
        return self.contacts.get(user_id)

    async def insert(self, notification: dict[str, Any]) -> bool:
        if any(n["event_id"] == notification["event_id"] for n in self.items.values()):
            return False
        self.items[notification["_id"]] = dict(notification)
        return True

    async def get_by_event(self, event_id: str) -> dict[str, Any] | None:
        return next((n for n in self.items.values() if n["event_id"] == event_id), None)

    async def mark_sent(self, notification_id: str, sent_at: datetime) -> None:
        self.items[notification_id].update(status="sent", sent_at=sent_at)

    async def list_for_user(self, user_id: str, unread_only: bool, limit: int, offset: int) -> tuple[list[dict], int]:
        found = [n for n in self.items.values() if n["user_id"] == user_id and (not unread_only or not n["read"])]
        found.sort(key=lambda n: n["created_at"], reverse=True)
        return found[offset : offset + limit], len(found)

    async def mark_read(self, user_id: str, notification_id: str) -> bool:
        item = self.items.get(notification_id)
        if item is None or item["user_id"] != user_id:
            return False
        item["read"] = True
        return True

    async def unread_count(self, user_id: str) -> int:
        return sum(1 for n in self.items.values() if n["user_id"] == user_id and not n["read"])

    async def ping(self) -> None:
        return None

    async def close(self) -> None:
        return None
