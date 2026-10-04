"""Pydantic schemas for candidate endpoints."""

from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator


class CandidateCreate(BaseModel):
    """Payload for creating a candidate."""

    name: str = Field(min_length=1, max_length=255)
    email: EmailStr | None = None
    phone: str | None = Field(default=None, max_length=50)
    location: str | None = Field(default=None, max_length=255)

    @field_validator("name")
    @classmethod
    def require_non_blank_name(cls, value: str) -> str:
        cleaned_value = value.strip()
        if not cleaned_value:
            raise ValueError("must not be blank")
        return cleaned_value


class CandidateResponse(BaseModel):
    """Public candidate representation."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    email: str | None
    phone: str | None
    location: str | None
    resume_filename: str | None
    created_at: datetime
    updated_at: datetime


class CandidateDetailResponse(CandidateResponse):
    """Candidate representation for an individual resource."""

    resume_text: str | None = None


class JobCandidateResponse(BaseModel):
    """Candidate details together with job-specific association data."""

    model_config = ConfigDict(from_attributes=True)

    id: int
    job_id: int
    candidate_id: int
    match_score: float | None
    status: str
    recruiter_notes: str | None
    created_at: datetime
    candidate: CandidateResponse
