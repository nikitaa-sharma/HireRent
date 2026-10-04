"""Job database model."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import DateTime, String, Text, func
from sqlalchemy.ext.associationproxy import AssociationProxy, association_proxy
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.candidate import Candidate
    from app.models.job_candidate import JobCandidate


class Job(Base):
    """A job opening with its associated candidates."""

    __tablename__ = "jobs"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    description: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    job_candidates: Mapped[list[JobCandidate]] = relationship(
        back_populates="job", cascade="all, delete-orphan"
    )
    candidates: AssociationProxy[list[Candidate]] = association_proxy(
        "job_candidates", "candidate"
    )

    def __repr__(self) -> str:
        return f"Job(id={self.id!r}, title={self.title!r})"
