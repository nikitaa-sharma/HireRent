"""Schemas for side-by-side candidate comparison."""

from pydantic import BaseModel, Field

from app.schemas.match_evidence import EvidenceItem


class CandidateComparisonEntry(BaseModel):
    """One candidate's existing match and evidence for a job."""

    candidate_id: int
    candidate_name: str
    match_score: float = Field(ge=0, le=100)
    component_scores: dict[str, float]
    matched_required_skills: list[str] = Field(default_factory=list)
    missing_required_skills: list[str] = Field(default_factory=list)
    matched_preferred_skills: list[str] = Field(default_factory=list)
    experience_gap_years: float | None = None
    education_match: bool | None = None
    strengths: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[EvidenceItem] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)


class CandidateComparisonResponse(BaseModel):
    """Side-by-side comparison for one job."""

    job_id: int
    job_title: str
    candidates: list[CandidateComparisonEntry]
