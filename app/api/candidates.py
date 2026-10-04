"""Candidate API routes."""

from pathlib import Path
from uuid import uuid4

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import MAX_UPLOAD_SIZE_MB, UPLOAD_DIR
from app.database import get_db
from app.models import Candidate
from app.schemas.candidate import (
    CandidateCreate,
    CandidateDetailResponse,
    CandidateResponse,
)
from app.schemas.candidate_profile import CandidateProfile
from app.schemas.candidate_search import CandidateSearchResponse
from app.services.candidate_processor import process_candidate_resume
from app.services.candidate_search_service import search_candidates as search_candidate_records
from app.services import vector_store
from app.utils.resume_parser import extract_text_from_pdf

router = APIRouter(prefix="/api/candidates", tags=["Candidates"])

UPLOAD_CHUNK_SIZE = 1024 * 1024


@router.post("", response_model=CandidateResponse, status_code=status.HTTP_201_CREATED)
def create_candidate(
    payload: CandidateCreate, db: Session = Depends(get_db)
) -> Candidate:
    candidate = Candidate(**payload.model_dump())
    db.add(candidate)
    db.commit()
    db.refresh(candidate)
    return candidate


@router.get("", response_model=list[CandidateResponse])
def list_candidates(db: Session = Depends(get_db)) -> list[Candidate]:
    return list(db.scalars(select(Candidate).order_by(Candidate.id)).all())


@router.post(
    "/upload-resume",
    response_model=CandidateDetailResponse,
    status_code=status.HTTP_201_CREATED,
)
async def upload_resume(
    file: UploadFile = File(...),
    name: str | None = Form(default=None),
    email: str | None = Form(default=None),
    phone: str | None = Form(default=None),
    location: str | None = Form(default=None),
    db: Session = Depends(get_db),
) -> Candidate:
    """Save a PDF resume, extract its text, and create a candidate."""

    original_filename = file.filename or ""
    content_type = (file.content_type or "").lower()
    if not original_filename.lower().endswith(".pdf") and content_type != "application/pdf":
        await file.close()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Only PDF resume files are accepted",
        )

    maximum_size = MAX_UPLOAD_SIZE_MB * 1024 * 1024
    UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
    saved_path = UPLOAD_DIR / f"{uuid4().hex}.pdf"
    bytes_written = 0

    try:
        with saved_path.open("wb") as destination:
            while chunk := await file.read(UPLOAD_CHUNK_SIZE):
                bytes_written += len(chunk)
                if bytes_written > maximum_size:
                    raise HTTPException(
                        status_code=status.HTTP_413_CONTENT_TOO_LARGE,
                        detail="Resume file exceeds the maximum upload size",
                    )
                destination.write(chunk)

        try:
            resume_text = extract_text_from_pdf(saved_path)
        except ValueError as error:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=str(error),
            ) from error

        if not resume_text or not resume_text.strip():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="The PDF does not contain meaningful text",
            )

        candidate_name = (name or "").strip() or "Unnamed Candidate"
        candidate = Candidate(
            name=candidate_name,
            email=(email or "").strip() or None,
            phone=(phone or "").strip() or None,
            location=(location or "").strip() or None,
            resume_filename=saved_path.name,
            resume_text=resume_text,
        )
        db.add(candidate)
        db.commit()
        db.refresh(candidate)
        return candidate
    except HTTPException:
        saved_path.unlink(missing_ok=True)
        raise
    except (OSError, SQLAlchemyError) as error:
        db.rollback()
        saved_path.unlink(missing_ok=True)
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Unable to save the resume",
        ) from error
    finally:
        await file.close()


@router.post("/{candidate_id}/process", response_model=CandidateProfile)
def process_candidate(candidate_id: int, db: Session = Depends(get_db)) -> CandidateProfile:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
        )
    if not candidate.resume_text or not candidate.resume_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Candidate does not have stored resume text",
        )
    try:
        return process_candidate_resume(
            candidate_id=candidate.id,
            name=candidate.name,
            email=candidate.email,
            phone=candidate.phone,
            location=candidate.location,
            resume_text=candidate.resume_text,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error


@router.post("/{candidate_id}/index")
def index_candidate(candidate_id: int, db: Session = Depends(get_db)) -> dict[str, object]:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
        )
    if not candidate.resume_text or not candidate.resume_text.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Candidate does not have stored resume text",
        )

    embedding_text = "\n".join(
        value for value in (candidate.name, candidate.location, candidate.resume_text) if value
    )
    try:
        vector_store.index_candidate(candidate.id, embedding_text)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return {"candidate_id": candidate.id, "status": "indexed"}


@router.get("/search", response_model=CandidateSearchResponse)
def search_candidates(
    q: str = Query(..., min_length=1),
    limit: int = Query(default=10, ge=1, le=100),
    skills: list[str] = Query(default=[]),
    min_experience_years: float | None = Query(default=None, ge=0),
    location: str | None = Query(default=None),
    db: Session = Depends(get_db),
) -> CandidateSearchResponse:
    if not q.strip():
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Search query must not be empty"
        )
    try:
        results = search_candidate_records(
            db=db,
            query=q,
            limit=limit,
            required_skills=skills,
            min_experience_years=min_experience_years,
            location=location,
        )
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)
        ) from error
    return CandidateSearchResponse(results=results)


@router.get("/{candidate_id}", response_model=CandidateDetailResponse)
def get_candidate(candidate_id: int, db: Session = Depends(get_db)) -> Candidate:
    candidate = db.get(Candidate, candidate_id)
    if candidate is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND, detail="Candidate not found"
        )
    return candidate
