from pydantic_settings import BaseSettings, SettingsConfigDict


class BaseServiceSettings(BaseSettings):
    """Settings shared by every service. Values come from environment variables."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    service_name: str = "service"
    service_version: str = "1.0.0"
    environment: str = "dev"
    log_level: str = "INFO"
