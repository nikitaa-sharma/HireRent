"""Schemas for stateless grounded recruiter chat."""

from pydantic import BaseModel, Field


class RecruiterChatRequest(BaseModel):
    """One recruiter question, optionally scoped to a job."""

    message: str = Field(min_length=1, max_length=4000)
    job_id: int | None = None


class RecruiterChatEvidence(BaseModel):
    """A factual source reference used to ground a chat answer."""

    candidate_id: int
    candidate_name: str
    source: str
    text: str


class RecruiterChatResponse(BaseModel):
    """Grounded answer and the candidates/evidence used for it."""

    answer: str
    candidate_ids: list[int] = Field(default_factory=list)
    evidence: list[RecruiterChatEvidence] = Field(default_factory=list)
