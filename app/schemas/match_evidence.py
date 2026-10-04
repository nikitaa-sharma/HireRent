"""Evidence-backed match explanation schemas."""

from pydantic import BaseModel, Field


class EvidenceItem(BaseModel):
    """One factual piece of job or resume evidence."""

    type: str
    text: str
    source: str
    confidence: float = Field(ge=0, le=1)


class MatchExplanation(BaseModel):
    """Recruiter-facing explanation of an existing match result."""

    job_id: int
    candidate_id: int
    match_score: float = Field(ge=0, le=100)
    summary: str
    strengths: list[EvidenceItem] = Field(default_factory=list)
    gaps: list[EvidenceItem] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    component_scores: dict[str, float]
