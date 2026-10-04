"""Candidate database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.job_candidate import JobCandidate


class Candidate(Base):
    """A candidate profile that can be considered for multiple jobs."""

    __tablename__ = "candidates"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    email: Mapped[str | None] = mapped_column(String(320), nullable=True)
    phone: Mapped[str | None] = mapped_column(String(50), nullable=True)
    location: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resume_filename: Mapped[str | None] = mapped_column(String(255), nullable=True)
    resume_text: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    job_candidates: Mapped[list[JobCandidate]] = relationship(
        back_populates="candidate", cascade="all, delete-orphan"
    )
    jobs: AssociationProxy[list[Job]] = association_proxy("job_candidates", "job")

    def __repr__(self) -> str:
        return f"Candidate(id={self.id!r}, name={self.name!r})"
