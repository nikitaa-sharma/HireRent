"""Job-candidate association model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, Float, ForeignKey, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.job import Job


class JobCandidate(Base):
    """Job-specific information for a candidate under consideration."""

    __tablename__ = "job_candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    job_id: Mapped[int] = mapped_column(ForeignKey("jobs.id"), nullable=False)
    candidate_id: Mapped[int] = mapped_column(ForeignKey("candidates.id"), nullable=False)
    match_score: Mapped[float | None] = mapped_column(Float, nullable=True)
    status: Mapped[str] = mapped_column(String(50), default="new", nullable=False)
    recruiter_notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    job: Mapped[Job] = relationship(back_populates="job_candidates")
    candidate: Mapped[Candidate] = relationship(back_populates="job_candidates")

    def __repr__(self) -> str:
        return f"JobCandidate(job_id={self.job_id!r}, candidate_id={self.candidate_id!r})"
