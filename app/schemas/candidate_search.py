"""Schemas for recruiter candidate search results."""

from pydantic import BaseModel, Field


class CandidateSearchResult(BaseModel):
    """A candidate returned by semantic search."""

    candidate_id: int
    name: str
    email: str | None = None
    location: str | None = None
    similarity_score: float = Field(ge=0, le=100)
    evidence: str | None = None
    entity_id: int | None = None


class CandidateSearchResponse(BaseModel):
    """Candidate search response preserving semantic result order."""

    results: list[CandidateSearchResult] = Field(default_factory=list)
