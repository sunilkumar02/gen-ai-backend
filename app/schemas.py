from datetime import datetime
import base64
import binascii
from uuid import UUID

from pydantic import BaseModel, ConfigDict, EmailStr, Field, SecretStr, field_validator


class ChatRequest(BaseModel):
    prompt: str
    model: str


class ChatResponse(BaseModel):
    prompt: str
    model: str
    response: str


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


class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=320, description="The user's email address.")
    password: SecretStr = Field(
        min_length=4, max_length=684,
        description="Standard Base64 encoding of the UTF-8 password; not a password hash.",
    )

    @field_validator("username")
    @classmethod
    def normalize_username(cls, value: str) -> str:
        value = value.strip().lower()
        if not value:
            raise ValueError("Username cannot be empty")
        return value

    @field_validator("password")
    @classmethod
    def decode_password(cls, value: SecretStr) -> SecretStr:
        try:
            decoded = base64.b64decode(
                value.get_secret_value().encode("ascii"), validate=True
            ).decode("utf-8")
        except (ValueError, binascii.Error, UnicodeError):
            raise ValueError("Password must be valid Base64-encoded UTF-8") from None
        if not 1 <= len(decoded) <= 128:
            raise ValueError("Decoded password must contain 1–128 characters")
        return SecretStr(decoded)


class ValidationIssue(BaseModel):
    location: list[str | int]
    message: str
    type: str


class ErrorInfo(BaseModel):
    code: str
    message: str
    details: list[ValidationIssue] = Field(default_factory=list)


class APIErrorResponse(BaseModel):
    detail: str
    error: ErrorInfo
    request_id: UUID
