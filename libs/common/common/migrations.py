"""Shared Alembic runner: every service's migrations/env.py just calls `run_migrations(Base.metadata)`."""

import asyncio
import os

from sqlalchemy import MetaData
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool


def run_migrations(target_metadata: MetaData) -> None:
    from alembic import context

    url = os.environ.get("DATABASE_URL") or context.config.get_main_option("sqlalchemy.url")
    if not url:
        raise RuntimeError("DATABASE_URL is not set")

    if context.is_offline_mode():
        context.configure(url=url, target_metadata=target_metadata, literal_binds=True)
        with context.begin_transaction():
            context.run_migrations()
        return

    def do_run(connection: Connection) -> None:
        context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
        with context.begin_transaction():
            context.run_migrations()

    async def run_async() -> None:
        engine = create_async_engine(url, poolclass=NullPool)
        async with engine.connect() as connection:
            await connection.run_sync(do_run)
        await engine.dispose()

    asyncio.run(run_async())
