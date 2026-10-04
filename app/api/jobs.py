"""Job and job-candidate API routes."""

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from app.database import get_db
from app.models import Candidate, Job, JobCandidate
from app.schemas.candidate import JobCandidateResponse
from app.schemas.candidate_comparison import CandidateComparisonResponse
from app.schemas.job import JobCreate, JobResponse
from app.schemas.job_requirements import JobRequirements
from app.schemas.match import MatchResult
from app.schemas.match_evidence import MatchExplanation
from app.schemas.recruiter_review import (
    JobReviewResponse,
    RecruiterReviewResponse,
    RecruiterReviewUpdate,
)
from app.services import evidence_service
from app.services.candidate_comparison_service import (
    ComparisonAssociationError,
    ComparisonCandidateNotFoundError,
    ComparisonValidationError,
    compare_candidates,
)
from app.services import matching_service
from app.services.job_processor import process_job_description
from app.services import vector_store

router = APIRouter(prefix="/api/jobs", tags=["Jobs"])


@router.post("", response_model=JobResponse, status_code=status.HTTP_201_CREATED)
def create_job(payload: JobCreate, db: Session = Depends(get_db)) -> Job:
    job = Job(title=payload.title, description=payload.description)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@router.get("", response_model=list[JobResponse])
def list_jobs(db: Session = Depends(get_db)) -> list[Job]:
    return list(db.scalars(select(Job).order_by(Job.id)).all())


@router.get("/{job_id}", response_model=JobResponse)
def get_job(job_id: int, db: Session = Depends(get_db)) -> Job:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return job


@router.post("/{job_id}/process", response_model=JobRequirements)
def process_job(job_id: int, db: Session = Depends(get_db)) -> JobRequirements:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    return process_job_description(title=job.title, description=job.description)


@router.post("/{job_id}/index")
def index_job(job_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    embedding_text = f"{job.title}\n{job.description}"
    try:
        vector_store.index_job(job.id, embedding_text)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return {"job_id": job.id, "status": "indexed"}


@router.post(
    "/{job_id}/candidates/{candidate_id}/match",
    response_model=MatchResult,
)
def match_candidate(
    job_id: int, candidate_id: int, db: Session = Depends(get_db)
) -> MatchResult:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    try:
        result = matching_service.match_candidate_to_job(job, candidate)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    association = db.scalar(
        select(JobCandidate).where(
            JobCandidate.job_id == job_id,
            JobCandidate.candidate_id == candidate_id,
        )
    )
    if association is None:
        association = JobCandidate(job=job, candidate=candidate)
        db.add(association)
    association.match_score = result.match_score
    db.commit()
    return result


@router.post("/{job_id}/match-candidates", response_model=list[MatchResult])
def match_all_candidates(job_id: int, db: Session = Depends(get_db)) -> list[MatchResult]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    candidates = list(db.scalars(select(Candidate).order_by(Candidate.id)).all())
    try:
        results = [matching_service.match_candidate_to_job(job, candidate) for candidate in candidates]
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error

    associations = {
        association.candidate_id: association
        for association in db.scalars(
            select(JobCandidate).where(JobCandidate.job_id == job_id)
        ).all()
    }
    for result, candidate in zip(results, candidates):
        association = associations.get(candidate.id)
        if association is None:
            association = JobCandidate(job=job, candidate=candidate)
            db.add(association)
        association.match_score = result.match_score
    db.commit()
    return results


@router.get(
    "/{job_id}/candidates/{candidate_id}/match",
    response_model=MatchExplanation,
)
def explain_match(
    job_id: int, candidate_id: int, db: Session = Depends(get_db)
) -> MatchExplanation:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    association = db.scalar(
        select(JobCandidate).where(
            JobCandidate.job_id == job_id,
            JobCandidate.candidate_id == candidate_id,
        )
    )
    if association is None or association.match_score is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Match result not found",
        )
    try:
        calculated_result = matching_service.match_candidate_to_job(job, candidate)
        result = calculated_result.model_copy(update={"match_score": association.match_score})
        return evidence_service.build_match_explanation(job, candidate, result)
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


@router.get("/{job_id}/match-explanations", response_model=list[MatchExplanation])
def explain_all_matches(job_id: int, db: Session = Depends(get_db)) -> list[MatchExplanation]:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    associations = db.scalars(
        select(JobCandidate)
        .join(Candidate)
        .where(JobCandidate.job_id == job_id, JobCandidate.match_score.is_not(None))
        .options(selectinload(JobCandidate.candidate))
        .order_by(Candidate.id)
    ).all()
    explanations: list[MatchExplanation] = []
    try:
        for association in associations:
            calculated_result = matching_service.match_candidate_to_job(job, association.candidate)
            result = calculated_result.model_copy(update={"match_score": association.match_score})
            explanations.append(
                evidence_service.build_match_explanation(job, association.candidate, result)
            )
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
    return explanations


@router.get("/{job_id}/compare", response_model=CandidateComparisonResponse)
def compare_job_candidates(
    job_id: int,
    candidate_ids: list[int] = Query(...),
    db: Session = Depends(get_db),
) -> CandidateComparisonResponse:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    try:
        return compare_candidates(db, job, candidate_ids)
    except (ComparisonCandidateNotFoundError, ComparisonAssociationError) as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except ComparisonValidationError as error:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(error)
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error


def _get_review_association(
    job_id: int, candidate_id: int, db: Session
) -> JobCandidate:
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    if db.get(Candidate, candidate_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")
    association = db.scalar(
        select(JobCandidate).where(
            JobCandidate.job_id == job_id,
            JobCandidate.candidate_id == candidate_id,
        )
    )
    if association is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Candidate is not associated with this job",
        )
    return association


@router.patch(
    "/{job_id}/candidates/{candidate_id}/review",
    response_model=RecruiterReviewResponse,
)
def update_recruiter_review(
    job_id: int,
    candidate_id: int,
    payload: RecruiterReviewUpdate,
    db: Session = Depends(get_db),
) -> JobCandidate:
    association = _get_review_association(job_id, candidate_id, db)
    supplied_fields = payload.model_dump(exclude_unset=True)
    if "status" in supplied_fields:
        association.status = payload.status.value if payload.status is not None else association.status
    if "recruiter_notes" in supplied_fields:
        association.recruiter_notes = payload.recruiter_notes
    db.commit()
    db.refresh(association)
    return association


@router.get(
    "/{job_id}/candidates/{candidate_id}/review",
    response_model=RecruiterReviewResponse,
)
def get_recruiter_review(
    job_id: int, candidate_id: int, db: Session = Depends(get_db)
) -> JobCandidate:
    return _get_review_association(job_id, candidate_id, db)


@router.get("/{job_id}/reviews", response_model=list[JobReviewResponse])
def list_job_reviews(job_id: int, db: Session = Depends(get_db)) -> list[JobReviewResponse]:
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")
    associations = db.scalars(
        select(JobCandidate)
        .join(Candidate)
        .where(JobCandidate.job_id == job_id)
        .options(selectinload(JobCandidate.candidate))
        .order_by(Candidate.id)
    ).all()
    return [
        JobReviewResponse(
            job_id=association.job_id,
            candidate_id=association.candidate_id,
            candidate_name=association.candidate.name,
            status=association.status,
            recruiter_notes=association.recruiter_notes,
            match_score=association.match_score,
        )
        for association in associations
    ]


@router.post(
    "/{job_id}/candidates/{candidate_id}",
    response_model=JobCandidateResponse,
    status_code=status.HTTP_201_CREATED,
)
def associate_candidate(
    job_id: int, candidate_id: int, db: Session = Depends(get_db)
) -> JobCandidate:
    job = db.get(Job, job_id)
    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found")

    existing_association = db.scalar(
        select(JobCandidate).where(
            JobCandidate.job_id == job_id,
            JobCandidate.candidate_id == candidate_id,
        )
    )
    if existing_association is not None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Candidate is already associated with this job",
        )

    association = JobCandidate(job=job, candidate=candidate)
    db.add(association)
    db.commit()
    db.refresh(association)
    return association


@router.get("/{job_id}/candidates", response_model=list[JobCandidateResponse])
def list_job_candidates(
    job_id: int, db: Session = Depends(get_db)
) -> list[JobCandidate]:
    if db.get(Job, job_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    associations = db.scalars(
        select(JobCandidate)
        .where(JobCandidate.job_id == job_id)
        .options(selectinload(JobCandidate.candidate))
        .order_by(JobCandidate.id)
    ).all()
    return list(associations)
