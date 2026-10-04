"""Structured candidate profile schema."""

from pydantic import BaseModel, Field


class CandidateProfile(BaseModel):
    """Deterministic, best-effort profile extracted from resume text."""

    candidate_id: int | None = None
    name: str
    email: str | None = None
    phone: str | None = None
    location: str | None = None
    skills: list[str] = Field(default_factory=list)
    experience_years: float | None = None
    education: list[str] = Field(default_factory=list)
    companies: list[str] = Field(default_factory=list)
    job_titles: list[str] = Field(default_factory=list)
    certifications: list[str] = Field(default_factory=list)
    summary: str | None = None
    keywords: list[str] = Field(default_factory=list)
