"""Deterministic candidate profile extraction helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.schemas.candidate_profile import CandidateProfile
from app.utils.skill_vocabulary import SKILL_VOCABULARY


SECTION_NAMES = {
    "summary": {"summary", "professional summary", "profile", "about me"},
    "experience": {"experience", "work experience", "employment", "professional experience"},
    "education": {"education", "academic background"},
    "certifications": {"certifications", "certificates", "licenses"},
}
SECTION_HEADER = re.compile(r"^\s*([A-Za-z][A-Za-z &/']{1,45})\s*:??\s*$")


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        cleaned = re.sub(r"\s+", " ", value).strip(" -•*|,")
        key = cleaned.casefold()
        if cleaned and key not in seen:
            seen.add(key)
            result.append(cleaned)
    return result


def _skill_pattern(skill: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(skill)}(?!\w)", re.IGNORECASE)


def _extract_sections(resume_text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {}
    current_section: str | None = None
    for raw_line in resume_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        header_match = SECTION_HEADER.match(line)
        if header_match:
            heading = header_match.group(1).casefold().strip()
            current_section = next(
                (name for name, aliases in SECTION_NAMES.items() if heading in aliases),
                None,
            )
            if current_section:
                sections.setdefault(current_section, [])
            continue
        if current_section:
            sections.setdefault(current_section, []).append(line)
    return sections


def _extract_skills(resume_text: str) -> list[str]:
    found: list[tuple[int, str]] = []
    for skill in SKILL_VOCABULARY:
        match = _skill_pattern(skill).search(resume_text)
        if match:
            found.append((match.start(), skill))
    return [skill for _position, skill in sorted(found)]


def _extract_experience_years(resume_text: str) -> float | None:
    patterns = (
        r"(?P<years>\d+(?:\.\d+)?)\s*\+?\s*years?\s*(?:of\s*)?experience",
        r"worked\s+(?:for\s+)?(?P<years>\d+(?:\.\d+)?)\s*years?",
        r"(?P<years>\d+(?:\.\d+)?)\s*years?\s+at\b",
    )
    matches: list[tuple[int, int, float]] = []
    for pattern in patterns:
        for match in re.finditer(pattern, resume_text, re.IGNORECASE):
            value = float(match.group("years"))
            matches.append((match.start(), match.end(), value))

    non_overlapping: list[tuple[int, int, float]] = []
    for start, end, value in sorted(matches):
        if not any(start < existing_end and end > existing_start for existing_start, existing_end, _ in non_overlapping):
            non_overlapping.append((start, end, value))
    if not non_overlapping:
        return None
    return max(value for _start, _end, value in non_overlapping)


def _extract_education(resume_text: str, sections: dict[str, list[str]]) -> list[str]:
    education_lines = sections.get("education", [])
    if education_lines:
        return _unique(education_lines)

    terms = (
        r"Bachelor(?:'s)?(?:\s+degree)?",
        r"Master(?:'s)?(?:\s+degree)?",
        r"B\.\s?Tech\.?",
        r"B\.\s?E\.?",
        r"B\.\s?Sc\.?",
        r"BCA",
        r"M\.\s?Tech\.?",
        r"M\.\s?E\.?,?",
        r"M\.\s?Sc\.?",
        r"MCA",
        r"MBA",
        r"Ph\.?D\.?,?",
    )
    found: list[str] = []
    for pattern in terms:
        for match in re.finditer(pattern, resume_text, re.IGNORECASE):
            found.append(match.group(0).rstrip(","))
    return _unique(found)


def _extract_employment_lines(sections: dict[str, list[str]]) -> list[str]:
    return sections.get("experience", [])


def _extract_companies(experience_lines: list[str]) -> list[str]:
    companies: list[str] = []
    for line in experience_lines:
        at_match = re.search(r"\b(?:at|@)\s+([A-Z][A-Za-z0-9&.,' -]{1,60})", line)
        if at_match:
            companies.append(re.split(r"\s*[|(]|\s+-\s+|,\s+(?:20\d{2}|19\d{2})", at_match.group(1))[0])
            continue
        parts = [part.strip() for part in re.split(r"\s*[|]\s*", line)]
        if len(parts) >= 2 and not re.search(r"\b(?:19|20)\d{2}\b", parts[1]):
            companies.append(parts[1])
    return _unique(companies)


def _extract_job_titles(experience_lines: list[str]) -> list[str]:
    titles: list[str] = []
    title_pattern = re.compile(
        r"^\s*((?:(?:senior|junior|lead|principal|associate)\s+)?(?:(?:software|backend|frontend|full[- ]stack|data|product|project|technical|devops|cloud|qa|test|machine learning|marketing)\s+)?(?:engineer|developer|scientist|analyst|manager|designer|architect|administrator|consultant|intern|director))\b",
        re.IGNORECASE,
    )
    for line in experience_lines:
        first_part = re.split(r"\s*[|@]\s*|\s+at\s+", line, maxsplit=1, flags=re.IGNORECASE)[0]
        match = title_pattern.match(first_part)
        if match:
            titles.append(match.group(1))
    return _unique(titles)


def _extract_certifications(resume_text: str, sections: dict[str, list[str]]) -> list[str]:
    certifications = list(sections.get("certifications", []))
    explicit_pattern = re.compile(
        r"\b(?:AWS Certified[^\n,;]*|Google Cloud Certified[^\n,;]*|Microsoft Certified[^\n,;]*|Certified Kubernetes Administrator|PMP|Scrum Master)\b",
        re.IGNORECASE,
    )
    certifications.extend(match.group(0) for match in explicit_pattern.finditer(resume_text))
    return _unique(certifications)


def _extract_summary(sections: dict[str, list[str]]) -> str | None:
    summary_lines = sections.get("summary", [])
    return " ".join(summary_lines).strip() or None


def _extract_keywords(
    resume_text: str,
    skills: list[str],
    education: list[str],
    companies: list[str],
    job_titles: list[str],
    certifications: list[str],
) -> list[str]:
    stop_words = {
        "the", "and", "for", "with", "that", "this", "from", "have", "has",
        "years", "experience", "worked", "professional", "responsible", "using",
        "about", "summary", "education", "skills", "certifications",
    }
    words = re.findall(r"[A-Za-z][A-Za-z+#.-]{2,}", resume_text.casefold())
    meaningful_words = [word for word in words if word not in stop_words]
    return _unique(
        [*skills, *job_titles, *education, *certifications, *companies, *meaningful_words]
    )[:50]


def process_candidate_resume(
    candidate_id: int | None,
    name: str,
    email: str | None,
    phone: str | None,
    location: str | None,
    resume_text: str,
) -> CandidateProfile:
    """Extract a conservative structured profile from stored resume text."""

    if not resume_text or not resume_text.strip():
        raise ValueError("Resume text must not be empty")

    sections = _extract_sections(resume_text)
    skills = _extract_skills(resume_text)
    experience_lines = _extract_employment_lines(sections)
    education = _extract_education(resume_text, sections)
    companies = _extract_companies(experience_lines)
    job_titles = _extract_job_titles(experience_lines)
    certifications = _extract_certifications(resume_text, sections)
    return CandidateProfile(
        candidate_id=candidate_id,
        name=name,
        email=email,
        phone=phone,
        location=location,
        skills=skills,
        experience_years=_extract_experience_years(resume_text),
        education=education,
        companies=companies,
        job_titles=job_titles,
        certifications=certifications,
        summary=_extract_summary(sections),
        keywords=_extract_keywords(
            resume_text, skills, education, companies, job_titles, certifications
        ),
    )
