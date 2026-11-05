from common.config import BaseServiceSettings


class Settings(BaseServiceSettings):
    service_name: str = "catalog-service"
    database_url: str = "postgresql+asyncpg://catalog:catalog@localhost:5432/catalog"
    jwks_url: str = "http://auth-service:8000/api/auth/.well-known/jwks.json"
    grpc_port: int = 50051
    seed_demo_data: bool = True
