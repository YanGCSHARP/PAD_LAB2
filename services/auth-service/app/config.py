from pydantic import SecretStr

from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "auth-service"

    database_url: str = "postgresql+asyncpg://auth:auth@localhost:5432/auth"
    rabbitmq_url: str = "amqp://guest:guest@localhost:5672/"

    jwt_private_key_path: str = "/data/keys/jwt_private.pem"
    access_token_ttl_seconds: int = 900
    refresh_token_ttl_seconds: int = 7 * 24 * 3600
    bcrypt_rounds: int = 12

    # Bootstrap administrator (created on start-up if it does not exist).
    admin_email: str = "admin@ticketing.io"
    admin_password: SecretStr | None = None
    admin_full_name: str = "System Administrator"

    outbox_poll_interval: float = 0.5
