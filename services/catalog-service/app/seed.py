"""Demo data so the system is usable right after `docker compose up`."""

import logging
import uuid
from datetime import timedelta
from decimal import Decimal

from sqlalchemy import func, select

from common.db import Database, utcnow

from .models import Event, TicketCategory, Venue

logger = logging.getLogger(__name__)


def _categories(*items: tuple[str, str, int]) -> list[TicketCategory]:
    return [TicketCategory(id=uuid.uuid4(), name=n, price=Decimal(p), total=t, available=t) for n, p, t in items]


async def seed_demo_data(db: Database) -> None:
    async with db.sessionmaker() as session:
        if await session.scalar(select(func.count()).select_from(Venue)):
            return
        now = utcnow().replace(minute=0, second=0, microsecond=0)
        palace = Venue(id=uuid.uuid4(), name="Palatul Republicii", city="Chisinau", address="str. Maria Cibotari 16", capacity=1500, created_at=now)
        arena = Venue(id=uuid.uuid4(), name="Arena Chisinau", city="Chisinau", address="str. Ion Creanga 5", capacity=10000, created_at=now)
        theatre = Venue(id=uuid.uuid4(), name="Teatrul National", city="Balti", address="str. Independentei 1", capacity=600, created_at=now)
        session.add_all([palace, arena, theatre])
        session.add_all([
            Event(id=uuid.uuid4(), venue=arena, title="Rock Night 2026", category="concert", status="on_sale",
                  description="Большой рок-концерт под открытым небом.", starts_at=now + timedelta(days=30), created_at=now,
                  ticket_categories=_categories(("Fan zone", "450.00", 5000), ("Tribune", "300.00", 4000), ("VIP", "4500.00", 50))),
            Event(id=uuid.uuid4(), venue=palace, title="Symphony Evening", category="concert", status="on_sale",
                  description="Классическая музыка: Чайковский и Рахманинов.", starts_at=now + timedelta(days=14), created_at=now,
                  ticket_categories=_categories(("Parter", "600.00", 800), ("Balcony", "350.00", 600))),
            Event(id=uuid.uuid4(), venue=theatre, title="Hamlet", category="theatre", status="on_sale",
                  description="Спектакль по пьесе У. Шекспира.", starts_at=now + timedelta(days=21), created_at=now,
                  ticket_categories=_categories(("Standard", "200.00", 500), ("Last seats", "150.00", 3))),
        ])
        await session.commit()
        logger.info("Demo catalog data seeded")
