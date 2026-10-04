"""Deterministic evidence generation for candidate-job matches."""

from __future__ import annotations

import re

from app.models import Candidate, Job
from app.schemas.match import MatchResult
from app.schemas.match_evidence import EvidenceItem, MatchExplanation
from app.services.candidate_processor import process_candidate_resume
from app.services.job_processor import process_job_description


def _confidence(value: float) -> float:
    return max(0.0, min(1.0, value))


def _snippet(text: str, term: str) -> str | None:
    match = re.search(re.escape(term), text, re.IGNORECASE)
    if match is None:
        return None
    start = max(text.rfind(".", 0, match.start()), text.rfind("\n", 0, match.start())) + 1
    end_candidates = [position for position in (text.find(".", match.end()), text.find("\n", match.end())) if position != -1]
    end = min(end_candidates, default=len(text))
    snippet = text[start:end].strip()
    if len(snippet) > 250:
        snippet = text[max(start, match.start() - 100) : min(len(text), match.end() + 150)].strip()
    return snippet[:250].strip() or None


def find_resume_evidence(resume_text: str, terms: list[str]) -> list[EvidenceItem]:
    """Find short, verbatim resume snippets for the supplied terms."""

    evidence: list[EvidenceItem] = []
    seen: set[str] = set()
    for term in terms:
        snippet = _snippet(resume_text, term)
        if snippet is None or snippet.casefold() in seen:
            continue
        seen.add(snippet.casefold())
        evidence.append(
            EvidenceItem(
                type="resume_evidence",
                text=snippet,
                source="resume",
                confidence=0.95,
            )
        )
    return evidence


def _job_evidence(job_description: str, term: str) -> EvidenceItem | None:
    snippet = _snippet(job_description, term)
    if snippet is None:
        return None
    return EvidenceItem(
        type="job_requirement",
        text=snippet,
        source="job_description",
        confidence=0.95,
    )


def _summary(match_result: MatchResult) -> str:
    if match_result.match_score >= 80:
        opening = "Strong match"
    elif match_result.match_score >= 60:
        opening = "Moderate match"
    else:
        opening = "Limited match"

    reasons: list[str] = []
    if match_result.matched_required_skills and not match_result.missing_required_skills:
        reasons.append("required skills")
    elif match_result.matched_required_skills:
        reasons.append("some required skills")
    if match_result.experience_score >= 100:
        reasons.append("experience")
    if match_result.education_match is True:
        reasons.append("education")

    summary = f"{opening}"
    if reasons:
        summary += " based on " + " and ".join(reasons)
    if match_result.missing_required_skills:
        missing = ", ".join(match_result.missing_required_skills)
        summary += f", with missing required skill evidence for {missing}"
    elif match_result.experience_gap_years:
        summary += f", with an experience gap of approximately {match_result.experience_gap_years:g} years"
    elif match_result.education_match is None and match_result.education_score == 50:
        summary += ", with no explicit education evidence"
    return summary + "."


def build_match_explanation(
    job: Job, candidate: Candidate, match_result: MatchResult
) -> MatchExplanation:
    """Build factual strengths, gaps, snippets, and a deterministic summary."""

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
    strengths: list[EvidenceItem] = []
    gaps: list[EvidenceItem] = []
    evidence = find_resume_evidence(
        candidate.resume_text,
        [*match_result.matched_required_skills, *match_result.matched_preferred_skills],
    )
    evidence.extend(
        item for skill in match_result.matched_required_skills
        if (item := _job_evidence(job.description, skill)) is not None
    )

    for skill in match_result.matched_required_skills:
        strengths.append(
            EvidenceItem(
                type="required_skill_match",
                text=f"{skill} found in the candidate resume",
                source="resume",
                confidence=0.95,
            )
        )
    for skill in match_result.matched_preferred_skills:
        strengths.append(
            EvidenceItem(
                type="preferred_skill_match",
                text=f"{skill} found in the candidate resume",
                source="resume",
                confidence=0.9,
            )
        )

    if match_result.semantic_score >= 70:
        strengths.append(
            EvidenceItem(
                type="semantic_relevance",
                text="The candidate resume has strong semantic similarity to the job description",
                source="resume_and_job_description",
                confidence=_confidence(match_result.semantic_score / 100),
            )
        )
    if (
        match_result.experience_gap_years == 0
        and profile.experience_years is not None
        and requirements.required_experience_years is not None
    ):
        strengths.append(
            EvidenceItem(
                type="experience_match",
                text=f"Candidate has {profile.experience_years:g} years of experience; job requires {requirements.required_experience_years:g} years",
                source="resume_and_job_description",
                confidence=0.95,
            )
        )
    elif (
        match_result.experience_gap_years is not None
        and profile.experience_years is not None
        and requirements.required_experience_years is not None
    ):
        gaps.append(
            EvidenceItem(
                type="experience_gap",
                text=f"Candidate has approximately {profile.experience_years:g} years; job requires {requirements.required_experience_years:g} years",
                source="resume_and_job_description",
                confidence=0.95,
            )
        )

    if match_result.education_match is True and profile.education:
        strengths.append(
            EvidenceItem(
                type="education_match",
                text=f"Candidate has {profile.education[0]} matching the job education requirement",
                source="resume_and_job_description",
                confidence=0.9,
            )
        )
    elif match_result.education_match is False:
        gaps.append(
            EvidenceItem(
                type="education_mismatch",
                text="Candidate education evidence does not match the stated job education requirement",
                source="resume_and_job_description",
                confidence=0.8,
            )
        )
    elif requirements.education:
        gaps.append(
            EvidenceItem(
                type="missing_education_evidence",
                text="Required education was not found in the resume",
                source="resume",
                confidence=0.9,
            )
        )

    for skill in match_result.missing_required_skills:
        gaps.append(
            EvidenceItem(
                type="missing_required_skill",
                text=f"Missing required skill: {skill}",
                source="job_description",
                confidence=1.0,
            )
        )
        job_item = _job_evidence(job.description, skill)
        if job_item is not None:
            evidence.append(job_item)

    return MatchExplanation(
        job_id=match_result.job_id,
        candidate_id=match_result.candidate_id,
        match_score=match_result.match_score,
        summary=_summary(match_result),
        strengths=strengths,
        gaps=gaps,
        evidence=evidence,
        component_scores={
            "semantic": match_result.semantic_score,
            "skills": match_result.skill_score,
            "experience": match_result.experience_score,
            "education": match_result.education_score,
        },
    )
