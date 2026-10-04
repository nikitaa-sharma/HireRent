from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Candidate, Job, JobCandidate
from app.services import matching_service
from app.services.candidate_comparison_service import compare_candidates


JOB_DESCRIPTION = "Required: Python, FastAPI. Preferred: Docker. 3 years of experience."
RESUME_TEXT = "Skills: Python, FastAPI, Docker\nExperience: 5 years of experience"


@pytest.fixture(autouse=True)
def deterministic_embeddings(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(matching_service.embedding_service, "embed_text", lambda _text: [1.0, 0.0])


@pytest.fixture
def comparison_context(
    tmp_path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'comparison-test.db'}",
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


def seed_comparison_data(session: Session, count: int = 3) -> tuple[int, list[int]]:
    job = Job(title="Backend Engineer", description=JOB_DESCRIPTION)
    session.add(job)
    session.commit()
    session.refresh(job)
    candidates: list[Candidate] = []
    for index in range(count):
        candidate = Candidate(name=f"Candidate {index + 1}", resume_text=RESUME_TEXT)
        session.add(candidate)
        session.commit()
        session.refresh(candidate)
        candidates.append(candidate)
    for index, candidate in enumerate(candidates):
        session.add(
            JobCandidate(
                job_id=job.id,
                candidate_id=candidate.id,
                match_score=70.0 + index,
                status="shortlisted" if index == 0 else "new",
                recruiter_notes="Existing note" if index == 0 else None,
            )
        )
    session.commit()
    return job.id, [candidate.id for candidate in candidates]


def test_valid_comparison_preserves_supplied_order_and_evidence(comparison_context) -> None:
    client, session_factory = comparison_context
    with session_factory() as session:
        job_id, candidate_ids = seed_comparison_data(session)

    response = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_ids[2]), ("candidate_ids", candidate_ids[0])],
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["job_id"] == job_id
    assert payload["job_title"] == "Backend Engineer"
    assert [entry["candidate_id"] for entry in payload["candidates"]] == [
        candidate_ids[2],
        candidate_ids[0],
    ]
    assert payload["candidates"][0]["match_score"] == 72.0
    assert payload["candidates"][0]["strengths"]
    assert payload["candidates"][0]["evidence"] is not None


def test_comparison_supports_five_candidates(comparison_context) -> None:
    client, session_factory = comparison_context
    with session_factory() as session:
        job_id, candidate_ids = seed_comparison_data(session, count=5)

    response = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_id) for candidate_id in candidate_ids],
    )

    assert response.status_code == 200
    assert [entry["candidate_id"] for entry in response.json()["candidates"]] == candidate_ids


def test_comparison_validation_rejects_invalid_cardinality_and_duplicates(comparison_context) -> None:
    client, session_factory = comparison_context
    with session_factory() as session:
        job_id, candidate_ids = seed_comparison_data(session)

    too_few = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_ids[0])],
    )
    duplicate = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_ids[0]), ("candidate_ids", candidate_ids[0])],
    )
    too_many = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_ids[0])] * 6,
    )

    assert too_few.status_code == 422
    assert duplicate.status_code == 422
    assert too_many.status_code == 422


def test_missing_job_candidate_and_association_return_errors(comparison_context) -> None:
    client, session_factory = comparison_context
    assert client.get(
        "/api/jobs/9999/compare", params=[("candidate_ids", 1), ("candidate_ids", 2)]
    ).status_code == 404
    with session_factory() as session:
        job_id, candidate_ids = seed_comparison_data(session, count=2)
        unassociated = Candidate(name="Unassociated", resume_text=RESUME_TEXT)
        session.add(unassociated)
        session.commit()
        session.refresh(unassociated)

    missing_candidate = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_ids[0]), ("candidate_ids", 9999)],
    )
    unassociated_response = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_ids[0]), ("candidate_ids", unassociated.id)],
    )

    assert missing_candidate.status_code == 404
    assert "not found" in missing_candidate.json()["detail"].lower()
    assert unassociated_response.status_code == 404
    assert "not associated" in unassociated_response.json()["detail"].lower()


def test_comparison_does_not_mutate_associations(comparison_context) -> None:
    client, session_factory = comparison_context
    with session_factory() as session:
        job_id, candidate_ids = seed_comparison_data(session, count=2)
        before = session.scalars(
            select(JobCandidate).where(JobCandidate.job_id == job_id)
        ).all()
        before_values = [
            (association.candidate_id, association.match_score, association.status, association.recruiter_notes)
            for association in before
        ]

    response = client.get(
        f"/api/jobs/{job_id}/compare",
        params=[("candidate_ids", candidate_id) for candidate_id in reversed(candidate_ids)],
    )
    assert response.status_code == 200

    with session_factory() as session:
        after = session.scalars(
            select(JobCandidate).where(JobCandidate.job_id == job_id)
        ).all()
        after_values = [
            (association.candidate_id, association.match_score, association.status, association.recruiter_notes)
            for association in after
        ]

    assert after_values == before_values


def test_comparison_route_is_in_openapi(comparison_context) -> None:
    paths = comparison_context[0].get("/openapi.json").json()["paths"]

    assert "/api/jobs/{job_id}/compare" in paths


def test_service_preserves_persisted_score_and_rejects_invalid_requests(comparison_context) -> None:
    _client, session_factory = comparison_context
    with session_factory() as session:
        job_id, candidate_ids = seed_comparison_data(session, count=2)
        job = session.get(Job, job_id)
        assert job is not None
        result = compare_candidates(session, job, [candidate_ids[1], candidate_ids[0]])

    assert [entry.candidate_id for entry in result.candidates] == [candidate_ids[1], candidate_ids[0]]
    assert [entry.match_score for entry in result.candidates] == [71.0, 70.0]
    with pytest.raises(ValueError):
        compare_candidates(session, job, candidate_ids[:1])
