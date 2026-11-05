from app.models import Base
from common.migrations import run_migrations

run_migrations(Base.metadata)
