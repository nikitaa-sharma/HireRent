"""Deterministic, explainable candidate-job matching."""

from __future__ import annotations

import math
import re

from app.models import Candidate, Job
from app.schemas.candidate_profile import CandidateProfile
from app.schemas.job_requirements import JobRequirements
from app.schemas.match import MatchResult
from app.services import embedding_service
from app.services.candidate_processor import process_candidate_resume
from app.services.job_processor import process_job_description

SEMANTIC_WEIGHT = 0.40
SKILL_WEIGHT = 0.35
EXPERIENCE_WEIGHT = 0.15
EDUCATION_WEIGHT = 0.10


def _normalise(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip().casefold()


def _cosine_similarity(first: list[float], second: list[float]) -> float:
    if len(first) != len(second) or not first:
        raise ValueError("Embedding vectors must have the same non-zero dimension")
    first_norm = math.sqrt(sum(value * value for value in first))
    second_norm = math.sqrt(sum(value * value for value in second))
    if first_norm == 0 or second_norm == 0:
        return 0.0
    return sum(left * right for left, right in zip(first, second)) / (first_norm * second_norm)


def _semantic_score(job: Job, candidate: Candidate) -> float:
    job_vector = embedding_service.embed_text(f"{job.title}\n{job.description}")
    candidate_vector = embedding_service.embed_text(candidate.resume_text or "")
    similarity = max(-1.0, min(1.0, _cosine_similarity(job_vector, candidate_vector)))
    # Map cosine similarity [-1, 1] linearly to the public score range [0, 100].
    return ((similarity + 1.0) / 2.0) * 100.0


def _skill_evidence(
    requirements: JobRequirements, profile: CandidateProfile
) -> tuple[float, list[str], list[str], list[str]]:
    candidate_skills = {_normalise(skill) for skill in profile.skills}
    matched_required = [
        skill for skill in requirements.required_skills if _normalise(skill) in candidate_skills
    ]
    missing_required = [
        skill for skill in requirements.required_skills if _normalise(skill) not in candidate_skills
    ]
    matched_preferred = [
        skill for skill in requirements.preferred_skills if _normalise(skill) in candidate_skills
    ]

    required_coverage = (
        len(matched_required) / len(requirements.required_skills)
        if requirements.required_skills
        else None
    )
    preferred_coverage = (
        len(matched_preferred) / len(requirements.preferred_skills)
        if requirements.preferred_skills
        else None
    )
    if required_coverage is None and preferred_coverage is None:
        score = 50.0
    elif required_coverage is None:
        score = preferred_coverage * 100.0
    elif preferred_coverage is None:
        score = required_coverage * 100.0
    else:
        score = (required_coverage * 0.70 + preferred_coverage * 0.30) * 100.0
    return score, matched_required, missing_required, matched_preferred


def _experience_evidence(
    requirement: float | None, candidate_experience: float | None
) -> tuple[float, float | None]:
    if requirement is None or candidate_experience is None:
        return 50.0, None
    gap = max(0.0, requirement - candidate_experience)
    if candidate_experience >= requirement:
        return 100.0, 0.0
    if requirement <= 0:
        return 100.0, gap
    return (candidate_experience / requirement) * 100.0, gap


def _education_evidence(
    required_education: list[str], candidate_education: list[str]
) -> tuple[float, bool | None]:
    if not required_education:
        return 50.0, None
    if not candidate_education:
        return 50.0, None

    candidate_text = " ".join(candidate_education).casefold()
    if any(_normalise(required) in candidate_text for required in required_education):
        return 100.0, True

    required_levels = {_education_level(value) for value in required_education}
    candidate_levels = {_education_level(value) for value in candidate_education}
    required_levels.discard(None)
    candidate_levels.discard(None)
    if required_levels & candidate_levels:
        return 100.0, True
    if required_levels and candidate_levels and required_levels.isdisjoint(candidate_levels):
        return 0.0, False
    return 50.0, None


def _education_level(value: str) -> str | None:
    text = value.casefold()
    if "phd" in text or "ph.d" in text:
        return "doctoral"
    if "master" in text or "m.tech" in text or "m.e" in text or "m.sc" in text or "mca" in text or "mba" in text:
        return "master"
    if "bachelor" in text or "b.tech" in text or "b.e" in text or "b.sc" in text or "bca" in text:
        return "bachelor"
    return None


def match_candidate_to_job(job: Job, candidate: Candidate) -> MatchResult:
    """Calculate a deterministic match score without mutating either model."""

    if not candidate.resume_text or not candidate.resume_text.strip():
        raise ValueError("Candidate does not have stored resume text")

    requirements = process_job_description(job.title, job.description)
    profile = process_candidate_resume(
        candidate_id=candidate.id,
        name=candidate.name,
        email=candidate.email,
        phone=candidate.phone,
        location=candidate.location,
        resume_text=candidate.resume_text,
    )
    semantic_score = _semantic_score(job, candidate)
    skill_score, matched_required, missing_required, matched_preferred = _skill_evidence(
        requirements, profile
    )
    experience_score, experience_gap = _experience_evidence(
        requirements.required_experience_years, profile.experience_years
    )
    education_score, education_match = _education_evidence(
        requirements.education, profile.education
    )
    match_score = (
        semantic_score * SEMANTIC_WEIGHT
        + skill_score * SKILL_WEIGHT
        + experience_score * EXPERIENCE_WEIGHT
        + education_score * EDUCATION_WEIGHT
    )
    return MatchResult(
        job_id=job.id,
        candidate_id=candidate.id,
        match_score=round(max(0.0, min(100.0, match_score)), 4),
        semantic_score=round(semantic_score, 4),
        skill_score=round(skill_score, 4),
        experience_score=round(experience_score, 4),
        education_score=round(education_score, 4),
        matched_required_skills=matched_required,
        missing_required_skills=missing_required,
        matched_preferred_skills=matched_preferred,
        experience_gap_years=experience_gap,
        education_match=education_match,
    )
