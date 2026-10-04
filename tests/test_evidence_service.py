from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Candidate, Job, JobCandidate
from app.services import matching_service
from app.services.evidence_service import build_match_explanation, find_resume_evidence
from app.services.matching_service import match_candidate_to_job


JOB_TEXT = """Required: Python, Kubernetes. Preferred: Docker.
3 years of experience. Bachelor's degree required."""
RESUME_TEXT = """Summary:
Backend engineer building reliable services.

Skills:
Python and Docker

Experience:
5 years of experience

Education:
B.Tech in Computer Science
"""


@pytest.fixture(autouse=True)
def deterministic_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(matching_service.embedding_service, "embed_text", lambda _text: [1.0, 0.0])


@pytest.fixture
def evidence_client(
    tmp_path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'evidence-test.db'}",
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


def make_models() -> tuple[Job, Candidate]:
    return (
        Job(id=10, title="Platform Engineer", description=JOB_TEXT),
        Candidate(id=20, name="Candidate", resume_text=RESUME_TEXT),
    )


def test_strong_explanation_preserves_scores_and_summary() -> None:
    job, candidate = make_models()
    match_result = match_candidate_to_job(job, candidate)
    explanation = build_match_explanation(job, candidate, match_result)

    assert explanation.match_score == match_result.match_score
    assert explanation.component_scores == {
        "semantic": match_result.semantic_score,
        "skills": match_result.skill_score,
        "experience": match_result.experience_score,
        "education": match_result.education_score,
    }
    assert "Strong match" in explanation.summary
    assert any("Python" in item.text for item in explanation.strengths)
    assert any(item.type == "experience_match" for item in explanation.strengths)
    assert any(item.type == "education_match" for item in explanation.strengths)


def test_missing_required_and_preferred_evidence() -> None:
    job, candidate = make_models()
    match_result = match_candidate_to_job(job, candidate)
    explanation = build_match_explanation(job, candidate, match_result)

    assert any("Missing required skill: Kubernetes" == item.text for item in explanation.gaps)
    assert any("Docker found" in item.text for item in explanation.strengths)
    assert "Kubernetes" in explanation.summary


def test_missing_education_evidence() -> None:
    job, candidate = make_models()
    candidate.resume_text = "Skills: Python\nExperience: 5 years of experience"
    match_result = match_candidate_to_job(job, candidate)
    explanation = build_match_explanation(job, candidate, match_result)

    assert any(item.type == "missing_education_evidence" for item in explanation.gaps)


def test_resume_snippets_are_verbatim_and_unknown_terms_are_omitted() -> None:
    found = find_resume_evidence(RESUME_TEXT, ["Python", "not-present"])

    assert len(found) == 1
    assert found[0].source == "resume"
    assert "Python and Docker" in found[0].text
    assert all(len(item.text) <= 250 for item in found)
    assert all(0 <= item.confidence <= 1 for item in found)


def test_api_explanation_is_read_only_and_batch_is_ordered(evidence_client) -> None:
    client, session_factory = evidence_client
    with session_factory() as session:
        job = Job(title="Platform Engineer", description=JOB_TEXT)
        session.add(job)
        session.commit()
        session.refresh(job)
        first = Candidate(name="First", resume_text=RESUME_TEXT)
        second = Candidate(name="Second", resume_text=RESUME_TEXT)
        session.add_all([first, second])
        session.commit()
        session.refresh(first)
        session.refresh(second)
        session.add_all(
            [
                JobCandidate(
                    job_id=job.id,
                    candidate_id=first.id,
                    match_score=88.5,
                    status="shortlisted",
                    recruiter_notes="Keep notes",
                ),
                JobCandidate(job_id=job.id, candidate_id=second.id, match_score=None),
            ]
        )
        session.commit()
        job_id, first_id, second_id = job.id, first.id, second.id

    before = None
    with session_factory() as session:
        association = session.scalar(
            select(JobCandidate).where(
                JobCandidate.job_id == job_id,
                JobCandidate.candidate_id == first_id,
            )
        )
        before = (association.match_score, association.status, association.recruiter_notes)

    response = client.get(f"/api/jobs/{job_id}/candidates/{first_id}/match")
    batch = client.get(f"/api/jobs/{job_id}/match-explanations")

    assert response.status_code == 200
    assert response.json()["match_score"] == 88.5
    assert batch.status_code == 200
    assert [item["candidate_id"] for item in batch.json()] == [first_id]
    with session_factory() as session:
        association = session.scalar(
            select(JobCandidate).where(
                JobCandidate.job_id == job_id,
                JobCandidate.candidate_id == first_id,
            )
        )
        assert (association.match_score, association.status, association.recruiter_notes) == before
    assert second_id != first_id


def test_api_missing_job_candidate_and_association_return_404(evidence_client) -> None:
    client, session_factory = evidence_client
    assert client.get("/api/jobs/9999/candidates/1/match").status_code == 404
    with session_factory() as session:
        job = Job(title="Engineer", description="Python")
        candidate = Candidate(name="Candidate", resume_text=RESUME_TEXT)
        session.add_all([job, candidate])
        session.commit()
        session.refresh(job)
        session.refresh(candidate)
        job_id, candidate_id = job.id, candidate.id

    assert client.get(f"/api/jobs/{job_id}/candidates/9999/match").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/candidates/{candidate_id}/match").status_code == 404
    assert client.get(f"/api/jobs/{job_id}/match-explanations").status_code == 200


def test_evidence_routes_are_in_openapi(evidence_client) -> None:
    paths = evidence_client[0].get("/openapi.json").json()["paths"]

    assert "/api/jobs/{job_id}/candidates/{candidate_id}/match" in paths
    assert "/api/jobs/{job_id}/match-explanations" in paths
