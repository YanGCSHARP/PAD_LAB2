import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class ProfileOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    user_id: uuid.UUID
    email: str
    full_name: str
    phone: str | None
    city: str | None
    role: str
    created_at: datetime
    updated_at: datetime


class ProfileUpdate(BaseModel):
    full_name: str | None = Field(None, min_length=1, max_length=200)
    phone: str | None = Field(None, pattern=r"^\+?[0-9\- ]{6,20}$", examples=["+37369123456"])
    city: str | None = Field(None, min_length=1, max_length=100, examples=["Chisinau"])
