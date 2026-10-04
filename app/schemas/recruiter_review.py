"""Schemas for job-specific recruiter review data."""

from enum import Enum

from pydantic import BaseModel, ConfigDict, Field


class CandidateStatus(str, Enum):
    """Supported recruiter workflow statuses."""

    NEW = "new"
    REVIEWING = "reviewing"
    SHORTLISTED = "shortlisted"
    INTERVIEW = "interview"
    REJECTED = "rejected"
    HIRED = "hired"


class RecruiterReviewUpdate(BaseModel):
    """Fields that may be updated on a job-candidate association."""

    status: CandidateStatus | None = None
    recruiter_notes: str | None = None


class RecruiterReviewResponse(BaseModel):
    """Review data for one candidate under one job."""

    model_config = ConfigDict(from_attributes=True)

    job_id: int
    candidate_id: int
    status: CandidateStatus
    recruiter_notes: str | None


class JobReviewResponse(BaseModel):
    """Review data and match score for one job's candidates."""

    job_id: int
    candidate_id: int
    candidate_name: str
    status: CandidateStatus
    recruiter_notes: str | None
    match_score: float | None = Field(default=None, ge=0, le=100)
