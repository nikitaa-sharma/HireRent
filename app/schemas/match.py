"""Candidate-job match result schema."""

from pydantic import BaseModel, Field


class MatchResult(BaseModel):
    """Explainable, job-specific candidate matching result."""

    job_id: int
    candidate_id: int
    match_score: float = Field(ge=0, le=100)
    semantic_score: float = Field(ge=0, le=100)
    skill_score: float = Field(ge=0, le=100)
    experience_score: float = Field(ge=0, le=100)
    education_score: float = Field(ge=0, le=100)
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    experience_gap_years: float | None = None
    education_match: bool | None = None
