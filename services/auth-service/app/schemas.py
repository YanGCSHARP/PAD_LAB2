import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(min_length=8, max_length=72, examples=["Secret123"])
    full_name: str = Field(min_length=1, max_length=200, examples=["Ivan Petrov"])

    @field_validator("password")
    @classmethod
    def password_strength(cls, value: str) -> str:
        if len(value.encode()) > 72:
            raise ValueError("password is too long")
        if not any(c.isalpha() for c in value) or not any(c.isdigit() for c in value):
            raise ValueError("password must contain letters and digits")
        return value

    @field_validator("full_name")
    @classmethod
    def strip_name(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("full_name must not be blank")
        return value


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=255, examples=["admin@ticketing.io"])
    password: str = Field(min_length=1, max_length=128)


class RefreshRequest(BaseModel):
    refresh_token: str = Field(min_length=10, max_length=512)


class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    email: str
    full_name: str
    role: str
    is_active: bool
    created_at: datetime


class RoleUpdate(BaseModel):
    role: Literal["user", "admin"]


class JWKS(BaseModel):
    keys: list[dict]
