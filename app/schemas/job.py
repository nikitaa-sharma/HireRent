"""Pydantic schemas for job endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


class JobCreate(BaseModel):
    """Payload for creating a job."""

    title: str = Field(min_length=1, max_length=255)
    description: str = Field(min_length=1)

    @field_validator("title", "description")
    @classmethod
    def require_non_blank_text(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("must not be blank")
        return cleaned_value


class JobResponse(BaseModel):
    """Public job representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    title: str
    description: str
    created_at: datetime
    updated_at: datetime
