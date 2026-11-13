from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class CreateThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: UUID
    title: str = Field(min_length=1, max_length=255)


class UpdateThread(BaseModel):
    model_config = ConfigDict(extra="forbid")

    title: str | None = Field(default=None, min_length=1, max_length=255)


class ReadThread(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    user_id: UUID
    title: str | None
    created_at: datetime
    updated_at: datetime
