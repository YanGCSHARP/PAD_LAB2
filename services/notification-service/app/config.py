from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "notification-service"
    mongo_url: str = "mongodb://localhost:27017"
    mongo_db: str = "notifications"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"
    jwks_url: str = "http://auth-service:8000/api/auth/.well-known/jwks.json"
    events_queue: str = "notification-service.events"
