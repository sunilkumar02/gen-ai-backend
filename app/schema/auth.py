import base64
import binascii

from pydantic import BaseModel, ConfigDict, Field, SecretStr, field_validator


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
