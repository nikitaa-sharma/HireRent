"""Deterministic job description processing helpers."""

from __future__ import annotations

import re
from collections.abc import Iterable

from app.schemas.job_requirements import JobRequirements
from app.utils.skill_vocabulary import SKILL_VOCABULARY


SKILL_DICTIONARY = SKILL_VOCABULARY

EDUCATION_TERMS: tuple[str, ...] = (
    "Bachelor's degree",
    "Master's degree",
    "MBA",
    "B.Tech",
    "M.Tech",
    "Bachelor of Science",
    "Master of Science",
    "PhD",
)

EMPLOYMENT_TYPES: tuple[tuple[str, str], ...] = (
    ("full-time", "Full-time"),
    ("full time", "Full-time"),
    ("part-time", "Part-time"),
    ("part time", "Part-time"),
    ("contract", "Contract"),
    ("internship", "Internship"),
)

REQUIRED_MARKERS = ("required", "must have", "mandatory", "requirements", "essential")
PREFERRED_MARKERS = ("preferred", "nice to have", "bonus", "desirable", "plus")
RESPONSIBILITY_HEADERS = (
    "responsibilities",
    "what you'll do",
    "what you will do",
    "duties",
    "role and responsibilities",
)
HEADER_PATTERN = re.compile(
    r"^\s*(?:requirements?|qualifications?|responsibilities|what you(?:'ll| will) do|duties|role and responsibilities)\s*:??\s*$",
    re.IGNORECASE,
)
STOP_HEADERS = re.compile(
    r"^\s*(?:requirements?|qualifications?|responsibilities|what you(?:'ll| will) do|duties|role and responsibilities|education|benefits?)\s*:??\s*$",
    re.IGNORECASE,
)


def _clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value).strip()


def _unique(values: Iterable[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        key = value.casefold()
        if key not in seen:
            seen.add(key)
            result.append(value)
    return result


def _skill_pattern(skill: str) -> re.Pattern[str]:
    return re.compile(rf"(?<!\w){re.escape(skill)}(?!\w)", re.IGNORECASE)


def _skill_context(description: str, start: int, end: int) -> str:
    sentence_start = max(
        description.rfind(".", 0, start),
        description.rfind("\n", 0, start),
        description.rfind(";", 0, start),
    )
    sentence_end_candidates = [
        position
        for position in (
            description.find(".", end),
            description.find("\n", end),
            description.find(";", end),
        )
        if position != -1
    ]
    sentence_end = min(sentence_end_candidates, default=len(description))
    return description[sentence_start + 1 : sentence_end].casefold()


def _extract_required_skills(description: str) -> list[str]:
    required: list[str] = []
    for skill in SKILL_DICTIONARY:
        for match in _skill_pattern(skill).finditer(description):
            context = _skill_context(description, match.start(), match.end())
            if any(marker in context for marker in REQUIRED_MARKERS):
                required.append(skill)
                break
    return sorted(_unique(required), key=lambda skill: description.casefold().find(skill.casefold()))


def _extract_preferred_skills(description: str, required: list[str]) -> list[str]:
    preferred: list[str] = []
    required_keys = {skill.casefold() for skill in required}
    for skill in SKILL_DICTIONARY:
        if skill.casefold() in required_keys:
            continue
        for match in _skill_pattern(skill).finditer(description):
            context = _skill_context(description, match.start(), match.end())
            if any(marker in context for marker in PREFERRED_MARKERS) or not any(
                marker in context for marker in REQUIRED_MARKERS
            ):
                preferred.append(skill)
                break
    return sorted(_unique(preferred), key=lambda skill: description.casefold().find(skill.casefold()))


def _extract_experience_years(description: str) -> float | None:
    pattern = re.compile(
        r"(?:(?:minimum|at least)\s*)?(\d+(?:\.\d+)?)\s*\+?\s*years?\s*(?:of\s*)?experience",
        re.IGNORECASE,
    )
    matches = list(pattern.finditer(description))
    if not matches:
        return None

    required_matches = [
        match
        for match in matches
        if re.search(r"minimum|at least|\+", match.group(0), re.IGNORECASE)
    ]
    selected = required_matches or matches
    return max(float(match.group(1)) for match in selected)


def _extract_education(description: str) -> list[str]:
    found: list[str] = []
    for term in EDUCATION_TERMS:
        if re.search(rf"(?<!\w){re.escape(term)}(?!\w)", description, re.IGNORECASE):
            found.append(term)
    return found


def _extract_locations(description: str) -> list[str]:
    locations: list[str] = []
    for match in re.finditer(
        r"(?:location|located|based)\s*(?:in|:|-)\s*([A-Za-z][A-Za-z .,'/-]{1,50})",
        description,
        re.IGNORECASE,
    ):
        location = re.split(r"[.;\n]|\b(?:and|with|for)\b", match.group(1), maxsplit=1)[0]
        locations.append(_clean_text(location).strip(" ,-/"))
    if re.search(r"\bremote\b", description, re.IGNORECASE):
        locations.append("Remote")
    return _unique(location for location in locations if location)


def _extract_employment_type(description: str) -> str | None:
    for marker, label in EMPLOYMENT_TYPES:
        if re.search(rf"\b{re.escape(marker)}\b", description, re.IGNORECASE):
            return label
    return None


def _extract_responsibilities(description: str) -> list[str]:
    lines = [line.strip() for line in description.splitlines()]
    responsibilities: list[str] = []
    in_section = False
    for line in lines:
        if not line:
            continue
        if HEADER_PATTERN.match(line):
            in_section = line.rstrip(":").casefold() in {
                header.casefold() for header in RESPONSIBILITY_HEADERS
            }
            continue
        if in_section and STOP_HEADERS.match(line):
            break
        if in_section and (line.startswith(("-", "*", "•")) or len(line) > 20):
            responsibilities.append(line.lstrip("-*• ").strip())
    return _unique(responsibilities)


def _extract_keywords(description: str, skills: list[str], education: list[str]) -> list[str]:
    words = re.findall(r"[A-Za-z][A-Za-z+#.-]{2,}", description.casefold())
    stop_words = {
        "the", "and", "for", "with", "that", "this", "are", "you", "will",
        "our", "from", "have", "has", "years", "experience", "work", "role",
        "must", "should", "required", "preferred", "into", "their", "your",
    }
    keywords = [word for word in words if word not in stop_words]
    return _unique([*skills, *education, *keywords])[:50]


def process_job_description(title: str, description: str) -> JobRequirements:
    """Process a job description using conservative local heuristics."""

    clean_title = title.strip() if title else ""
    clean_description = description.strip() if description else ""
    if not clean_title:
        raise ValueError("Job title must not be empty")
    if not clean_description:
        raise ValueError("Job description must not be empty")

    required_skills = _extract_required_skills(clean_description)
    preferred_skills = _extract_preferred_skills(clean_description, required_skills)
    education = _extract_education(clean_description)
    all_skills = _unique([*required_skills, *preferred_skills])
    return JobRequirements(
        job_title=clean_title,
        required_skills=required_skills,
        preferred_skills=preferred_skills,
        required_experience_years=_extract_experience_years(clean_description),
        education=education,
        locations=_extract_locations(clean_description),
        employment_type=_extract_employment_type(clean_description),
        responsibilities=_extract_responsibilities(clean_description),
        keywords=_extract_keywords(clean_description, all_skills, education),
    )
