from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class UserCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr
    password: SecretStr = Field(min_length=12, max_length=128)
    name: str | None = Field(default=None, max_length=255)

    @field_validator("email")
    @classmethod
    def normalize_email(cls, value: str) -> str:
        return value.lower()


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    email: EmailStr | None = None
    password: SecretStr | None = Field(default=None, min_length=12, max_length=128)
    name: str | None = Field(default=None, max_length=255)

    @field_validator("email", "password")
    @classmethod
    def reject_null_credentials(cls, value):
        if value is None:
            raise ValueError("Email and password cannot be null")
        return value.lower() if isinstance(value, str) else value


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    email: str
    name: str | None
    created_at: datetime
    updated_at: datetime
