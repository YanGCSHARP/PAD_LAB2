from decimal import Decimal

from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "payment-service"
    database_url: str = "postgresql+asyncpg://payment:payment@localhost:5432/payment"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    jwks_url: str = "http://auth-service:8000/api/auth/.well-known/jwks.json"
    events_queue: str = "payment-service.events"
    outbox_poll_interval: float = 0.5

    # Simulated payment provider
    provider_latency_ms: int = 300
    decline_above_amount: Decimal = Decimal("10000.00")
