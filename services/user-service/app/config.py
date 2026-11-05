from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "user-service"
    database_url: str = "postgresql+asyncpg://users:users@localhost:5432/users"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    jwks_url: str = "http://auth-service:8000/api/auth/.well-known/jwks.json"
    events_queue: str = "user-service.events"
