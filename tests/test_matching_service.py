from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Candidate, Job, JobCandidate
from app.services import matching_service
from app.services.matching_service import match_candidate_to_job


STRONG_JOB = """Required: Python, FastAPI. Preferred: Docker.
5 years of experience. Bachelor's degree required."""
STRONG_RESUME = """Skills: Python, FastAPI, Docker
Experience:
5 years of experience
Education:
Bachelor's degree"""


@pytest.fixture(autouse=True)
def deterministic_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        matching_service.embedding_service,
        "embed_text",
        lambda text: [1.0, 0.0] if text else (_ for _ in ()).throw(ValueError("empty")),
    )


@pytest.fixture
def matching_client(
    tmp_path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'matching-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app), test_session
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def make_models(job_description: str = STRONG_JOB, resume_text: str = STRONG_RESUME):
    return (
        Job(id=1, title="Backend Engineer", description=job_description),
        Candidate(id=2, name="Candidate", resume_text=resume_text),
    )


def test_strong_match_is_deterministic_and_bounded() -> None:
    job, candidate = make_models()

    first = match_candidate_to_job(job, candidate)
    second = match_candidate_to_job(job, candidate)

    assert first == second
    assert first.match_score == 100.0
    assert 0 <= first.match_score <= 100
    assert first.matched_required_skills == ["Python", "FastAPI"]
    assert first.missing_required_skills == []
    assert first.matched_preferred_skills == ["Docker"]
    assert first.experience_score == 100.0
    assert first.education_match is True


def test_missing_required_and_preferred_skills_are_reported() -> None:
    job, candidate = make_models(
        resume_text="Skills: Python\nExperience: 5 years of experience\nEducation: Bachelor's degree"
    )

    result = match_candidate_to_job(job, candidate)

    assert result.matched_required_skills == ["Python"]
    assert result.missing_required_skills == ["FastAPI"]
    assert result.matched_preferred_skills == []
    assert result.skill_score < 100


def test_experience_below_requirement_and_unknown_experience() -> None:
    job, candidate = make_models(
        resume_text="Skills: Python, FastAPI\nExperience: 2 years of experience"
    )
    below_result = match_candidate_to_job(job, candidate)
    unknown_job, unknown_candidate = make_models(
        job_description="Required: Python.", resume_text="Skills: Python"
    )
    unknown_result = match_candidate_to_job(unknown_job, unknown_candidate)

    assert below_result.experience_gap_years == 3.0
    assert below_result.experience_score == 40.0
    assert unknown_result.experience_score == 50.0
    assert unknown_result.experience_gap_years is None


def test_education_match_and_missing_evidence() -> None:
    job, candidate = make_models()
    matched = match_candidate_to_job(job, candidate)
    unknown_job, unknown_candidate = make_models(resume_text="Skills: Python, FastAPI")
    unknown = match_candidate_to_job(unknown_job, unknown_candidate)

    assert matched.education_score == 100.0
    assert matched.education_match is True
    assert unknown.education_score == 50.0
    assert unknown.education_match is None


def test_no_skill_or_experience_requirements_are_neutral() -> None:
    job, candidate = make_models(
        job_description="Build reliable software systems.",
        resume_text="Skills: Python",
    )

    result = match_candidate_to_job(job, candidate)

    assert result.skill_score == 50.0
    assert result.experience_score == 50.0
    assert result.experience_gap_years is None


def test_empty_resume_is_rejected() -> None:
    job, candidate = make_models(resume_text=" ")

    with pytest.raises(ValueError, match="resume text"):
        match_candidate_to_job(job, candidate)


def _create_candidate(session: Session, name: str, resume_text: str) -> Candidate:
    candidate = Candidate(name=name, resume_text=resume_text)
    session.add(candidate)
    session.commit()
    session.refresh(candidate)
    return candidate


def test_single_match_persists_score_and_preserves_association_fields(matching_client) -> None:
    client, session_factory = matching_client
    with session_factory() as session:
        job = Job(title="Backend Engineer", description=STRONG_JOB)
        candidate = _create_candidate(session, "Candidate", STRONG_RESUME)
        session.add(job)
        session.commit()
        session.refresh(job)
        session.add(
            JobCandidate(
                job_id=job.id,
                candidate_id=candidate.id,
                status="shortlisted",
                recruiter_notes="Review carefully",
            )
        )
        session.commit()
        job_id, candidate_id = job.id, candidate.id

    response = client.post(f"/api/jobs/{job_id}/candidates/{candidate_id}/match")

    assert response.status_code == 200
    with session_factory() as session:
        association = session.scalar(
            select(JobCandidate).where(
                JobCandidate.job_id == job_id,
                JobCandidate.candidate_id == candidate_id,
            )
        )
        assert association is not None
        assert association.status == "shortlisted"
        assert association.recruiter_notes == "Review carefully"
        assert association.match_score == response.json()["match_score"]


def test_missing_resources_and_batch_order(matching_client) -> None:
    client, session_factory = matching_client
    with session_factory() as session:
        job = Job(title="Backend Engineer", description=STRONG_JOB)
        session.add(job)
        session.commit()
        session.refresh(job)
        first = _create_candidate(session, "First", STRONG_RESUME)
        second = _create_candidate(session, "Second", STRONG_RESUME)
        job_id = job.id
        first_id, second_id = first.id, second.id

    assert client.post("/api/jobs/9999/candidates/1/match").status_code == 404
    assert client.post(f"/api/jobs/{job_id}/candidates/9999/match").status_code == 404
    batch = client.post(f"/api/jobs/{job_id}/match-candidates")

    assert batch.status_code == 200
    assert [item["candidate_id"] for item in batch.json()] == [first_id, second_id]
    with session_factory() as session:
        associations = session.scalars(
            select(JobCandidate).where(JobCandidate.job_id == job_id)
        ).all()
        assert len(associations) == 2


def test_matching_routes_are_in_openapi(matching_client) -> None:
    paths = matching_client[0].get("/openapi.json").json()["paths"]

    assert "/api/jobs/{job_id}/candidates/{candidate_id}/match" in paths
    assert "/api/jobs/{job_id}/match-candidates" in paths
