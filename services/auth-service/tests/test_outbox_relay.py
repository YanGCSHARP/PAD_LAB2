from conftest import register

from app.models import OutboxEvent
from common.outbox import OutboxRelay
from common.testing import InMemoryBus


class FailingBus(InMemoryBus):
    async def publish(self, *args, **kwargs):
        raise ConnectionError("broker down")


async def test_relay_publishes_pending_events_once(client, app, outbox):
    await register(client)
    bus = InMemoryBus()
    relay = OutboxRelay(app.state.db, OutboxEvent, bus)

    assert await relay.run_once() == 1
    assert await relay.run_once() == 0
    assert bus.published[0]["event_type"] == "user.registered"
    assert (await outbox())[0].published_at is not None


async def test_relay_keeps_events_when_broker_is_down(client, app, outbox):
    await register(client)
    relay = OutboxRelay(app.state.db, OutboxEvent, FailingBus())
    try:
        await relay.run_once()
    except ConnectionError:
        pass
    assert (await outbox())[0].published_at is None  # will be retried later
