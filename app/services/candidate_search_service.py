"""Database-aware recruiter candidate search."""

from __future__ import annotations

import re

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import Candidate
from app.schemas.candidate_search import CandidateSearchResult
from app.services import vector_store
from app.services.candidate_processor import process_candidate_resume


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _similarity_score(raw_score: float) -> float:
    """Map cosine similarity [-1, 1] to a stable public score [0, 100]."""

    return round(max(0.0, min(100.0, ((raw_score + 1.0) / 2.0) * 100.0)), 4)


def _resume_evidence(candidate: Candidate, query: str) -> str | None:
    resume_text = candidate.resume_text or ""
    if not resume_text.strip():
        return None
    query_terms = [term for term in re.findall(r"[A-Za-z][A-Za-z+#.-]{2,}", query) if len(term) > 2]
    for term in query_terms:
        match = re.search(re.escape(term), resume_text, re.IGNORECASE)
        if match:
            start = max(resume_text.rfind(".", 0, match.start()), resume_text.rfind("\n", 0, match.start())) + 1
            end_candidates = [position for position in (resume_text.find(".", match.end()), resume_text.find("\n", match.end())) if position != -1]
            end = min(end_candidates, default=len(resume_text))
            return resume_text[start:end].strip()[:250]
    return resume_text.strip()[:250]


def _matches_filters(
    candidate: Candidate,
    query: str,
    required_skills: list[str],
    min_experience_years: float | None,
    location: str | None,
) -> bool:
    if location and location.casefold() not in (candidate.location or "").casefold():
        return False
    if not required_skills and min_experience_years is None:
        return True
    if not candidate.resume_text:
        return False
    profile = process_candidate_resume(
        candidate_id=candidate.id,
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
        location=candidate.location,
        resume_text=candidate.resume_text,
    )
    profile_skills = {_normalise(skill) for skill in profile.skills}
    if required_skills and any(_normalise(skill) not in profile_skills for skill in required_skills):
        return False
    if min_experience_years is not None and (
        profile.experience_years is None or profile.experience_years < min_experience_years
    ):
        return False
    return True


def search_candidates(
    db: Session,
    query: str,
    limit: int = 10,
    required_skills: list[str] | None = None,
    min_experience_years: float | None = None,
    location: str | None = None,
) -> list[CandidateSearchResult]:
    """Search FAISS candidates, then hydrate and optionally filter database records."""

    if not query or not query.strip():
        raise ValueError("Search query must not be empty")
    if limit < 1 or limit > 100:
        raise ValueError("Search limit must be between 1 and 100")

    # Fetch a wider semantic window so stale metadata or explicit filters do not
    # consume the requested number of valid database-backed results.
    metadata_results = vector_store.search_candidates(query, limit=100)
    candidate_ids = [
        int(item["entity_id"])
        for item in metadata_results
        if item.get("entity_type") == "candidate" and item.get("entity_id") is not None
    ]
    if not candidate_ids:
        return []
    candidates_by_id = {
        candidate.id: candidate
        for candidate in db.scalars(select(Candidate).where(Candidate.id.in_(candidate_ids))).all()
    }
    filters = required_skills or []
    results: list[CandidateSearchResult] = []
    for item in metadata_results:
        candidate_id = int(item["entity_id"])
        candidate = candidates_by_id.get(candidate_id)
        if candidate is None or not _matches_filters(
            candidate, query, filters, min_experience_years, location
        ):
            continue
        results.append(
            CandidateSearchResult(
                candidate_id=candidate.id,
                entity_id=candidate.id,
                name=candidate.name,
                email=candidate.email,
                location=candidate.location,
                similarity_score=_similarity_score(float(item.get("score", 0.0))),
                evidence=_resume_evidence(candidate, query),
            )
        )
        if len(results) >= limit:
            break
    return results
