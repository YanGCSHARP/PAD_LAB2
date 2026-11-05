from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "api-gateway"

    auth_service_url: str = "http://auth-service:8000"
    user_service_url: str = "http://user-service:8000"
    catalog_service_url: str = "http://catalog-service:8000"
    booking_service_url: str = "http://booking-service:8000"
    payment_service_url: str = "http://payment-service:8000"
    notification_service_url: str = "http://notification-service:8000"

    redis_url: str = "redis://redis:6379/0"
    jwks_url: str | None = None  # defaults to <auth_service_url>/api/auth/.well-known/jwks.json

    upstream_timeout_seconds: float = 5.0
    upstream_retries: int = 2
    circuit_failure_threshold: int = 5
    circuit_reset_seconds: float = 15.0

    rate_limit_per_minute: int = 120
    login_rate_limit_per_minute: int = 10

    cors_origins: str = "http://localhost:3000"  # comma-separated

    @property
    def upstream_urls(self) -> dict[str, str]:
        return {
            "auth": self.auth_service_url,
            "user": self.user_service_url,
            "catalog": self.catalog_service_url,
            "booking": self.booking_service_url,
            "payment": self.payment_service_url,
            "notification": self.notification_service_url,
        }

    @property
    def effective_jwks_url(self) -> str:
        return self.jwks_url or f"{self.auth_service_url}/api/auth/.well-known/jwks.json"
