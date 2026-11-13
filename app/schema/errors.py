from uuid import UUID

from pydantic import BaseModel, Field


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
