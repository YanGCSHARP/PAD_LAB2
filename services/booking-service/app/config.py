from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "booking-service"
    database_url: str = "postgresql+asyncpg://booking:booking@localhost:5432/booking"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    jwks_url: str = "http://auth-service:8000/api/auth/.well-known/jwks.json"
    events_queue: str = "booking-service.events"

    catalog_grpc_target: str = "catalog-service:50051"
    catalog_grpc_timeout_seconds: float = 3.0
    catalog_circuit_failure_threshold: int = 5
    catalog_circuit_reset_seconds: float = 15.0

    currency: str = "MDL"
    max_tickets_per_booking: int = 10
    outbox_poll_interval: float = 0.5
