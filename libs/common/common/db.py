from collections.abc import AsyncIterator
from datetime import UTC, datetime

from fastapi import Request
from sqlalchemy import MetaData, text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine


def utcnow() -> datetime:
    return datetime.now(UTC)


def ensure_aware(value: datetime) -> datetime:
    """SQLite returns naive datetimes; normalise everything to UTC-aware."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


class Database:
    def __init__(self, url: str, echo: bool = False) -> None:
        kwargs: dict = {}
        if url.startswith("postgresql"):
            kwargs = {
                "pool_size": 10,
                "max_overflow": 10,
                "pool_pre_ping": True,
                "pool_timeout": 5,
                "connect_args": {"timeout": 5, "command_timeout": 10},
            }
        self.url = url
        self.engine = create_async_engine(url, echo=echo, **kwargs)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def ping(self) -> None:
        async with self.engine.connect() as conn:
            await conn.execute(text("SELECT 1"))

    async def create_all(self, metadata: MetaData) -> None:
        async with self.engine.begin() as conn:
            await conn.run_sync(metadata.create_all)

    async def dispose(self) -> None:
        await self.engine.dispose()


async def get_session(request: Request) -> AsyncIterator[AsyncSession]:
    """FastAPI dependency: one session per request."""
    db: Database = request.app.state.db
    async with db.sessionmaker() as session:
        yield session
