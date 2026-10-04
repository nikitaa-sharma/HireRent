"""Structured requirements produced from a job description."""

from pydantic import BaseModel, Field


class JobRequirements(BaseModel):
    """Deterministic, best-effort job requirement extraction result."""

    job_title: str
    required_skills: list[str] = Field(default_factory=list)
    preferred_skills: list[str] = Field(default_factory=list)
    required_experience_years: float | None = None
    education: list[str] = Field(default_factory=list)
    locations: list[str] = Field(default_factory=list)
    employment_type: str | None = None
    responsibilities: list[str] = Field(default_factory=list)
    keywords: list[str] = Field(default_factory=list)
