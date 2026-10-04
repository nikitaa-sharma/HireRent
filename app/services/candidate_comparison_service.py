"""Read-only candidate comparison built from existing match data."""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candidate, Job, JobCandidate
from app.schemas.candidate_comparison import (
    CandidateComparisonEntry,
    CandidateComparisonResponse,
)
from app.services import evidence_service, matching_service


class ComparisonValidationError(ValueError):
    """Raised when requested candidates cannot be compared for a job."""


class ComparisonCandidateNotFoundError(ComparisonValidationError):
    """Raised when a requested candidate does not exist."""


class ComparisonAssociationError(ComparisonValidationError):
    """Raised when a candidate is not associated with the requested job."""


def compare_candidates(
    db: Session, job: Job, candidate_ids: list[int]
) -> CandidateComparisonResponse:
    """Build comparisons in the exact order supplied by the recruiter."""

    if len(candidate_ids) < 2 or len(candidate_ids) > 5:
        raise ComparisonValidationError("Compare between 2 and 5 candidates")
    if len(set(candidate_ids)) != len(candidate_ids):
        raise ComparisonValidationError("candidate_ids must not contain duplicates")

    entries: list[CandidateComparisonEntry] = []
    for candidate_id in candidate_ids:
        candidate = db.get(Candidate, candidate_id)
        if candidate is None:
            raise ComparisonCandidateNotFoundError(f"Candidate {candidate_id} not found")
        association = db.scalar(
            select(JobCandidate).where(
                JobCandidate.job_id == job.id,
                JobCandidate.candidate_id == candidate.id,
            )
        )
        if association is None:
            raise ComparisonAssociationError(
                f"Candidate {candidate_id} is not associated with this job"
            )

        result = matching_service.match_candidate_to_job(job, candidate)
        if association.match_score is not None:
            result = result.model_copy(update={"match_score": association.match_score})
        explanation = evidence_service.build_match_explanation(job, candidate, result)
        entries.append(
            CandidateComparisonEntry(
                candidate_id=candidate.id,
                candidate_name=candidate.name,
                match_score=explanation.match_score,
                component_scores=explanation.component_scores,
                matched_required_skills=result.matched_required_skills,
                missing_required_skills=result.missing_required_skills,
                matched_preferred_skills=result.matched_preferred_skills,
                experience_gap_years=result.experience_gap_years,
                education_match=result.education_match,
                strengths=explanation.strengths,
                gaps=explanation.gaps,
                evidence=explanation.evidence,
            )
        )

    return CandidateComparisonResponse(
        job_id=job.id,
        job_title=job.title,
        candidates=entries,
    )
