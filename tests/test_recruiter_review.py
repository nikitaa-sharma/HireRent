from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Candidate, Job, JobCandidate


@pytest.fixture
def review_context(
    tmp_path,
) -> Generator[tuple[TestClient, sessionmaker[Session]], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'review-test.db'}",
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


def seed_review_data(session: Session) -> tuple[int, int, int]:
    first_job = Job(title="Backend Engineer", description="Build APIs")
    second_job = Job(title="Platform Engineer", description="Build platforms")
    first_candidate = Candidate(name="First Candidate", resume_text="Python")
    second_candidate = Candidate(name="Second Candidate", resume_text="Docker")
    session.add_all([first_job, second_job, first_candidate, second_candidate])
    session.commit()
    session.refresh(first_job)
    session.refresh(second_job)
    session.refresh(first_candidate)
    session.refresh(second_candidate)
    session.add_all(
        [
            JobCandidate(
                job_id=first_job.id,
                candidate_id=first_candidate.id,
                match_score=82.5,
                status="reviewing",
                recruiter_notes="Initial review",
            ),
            JobCandidate(
                job_id=first_job.id,
                candidate_id=second_candidate.id,
                match_score=61.0,
                status="new",
                recruiter_notes=None,
            ),
            JobCandidate(
                job_id=second_job.id,
                candidate_id=first_candidate.id,
                match_score=44.0,
                status="interview",
                recruiter_notes="Different job context",
            ),
        ]
    )
    session.commit()
    return first_job.id, second_job.id, first_candidate.id


def test_update_status(review_context) -> None:
    client, session_factory = review_context
    with session_factory() as session:
        job_id, _second_job_id, candidate_id = seed_review_data(session)

    response = client.patch(
        f"/api/jobs/{job_id}/candidates/{candidate_id}/review",
        json={"status": "shortlisted"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "shortlisted"
    assert response.json()["recruiter_notes"] == "Initial review"


def test_update_notes_and_partial_updates_preserve_other_field(review_context) -> None:
    client, session_factory = review_context
    with session_factory() as session:
        job_id, _second_job_id, candidate_id = seed_review_data(session)

    notes_response = client.patch(
        f"/api/jobs/{job_id}/candidates/{candidate_id}/review",
        json={"recruiter_notes": "Discuss system design."},
    )
    status_response = client.patch(
        f"/api/jobs/{job_id}/candidates/{candidate_id}/review",
        json={"status": "interview"},
    )

    assert notes_response.status_code == 200
    assert notes_response.json()["status"] == "reviewing"
    assert notes_response.json()["recruiter_notes"] == "Discuss system design."
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "interview"
    assert status_response.json()["recruiter_notes"] == "Discuss system design."


def test_update_both_and_invalid_status(review_context) -> None:
    client, session_factory = review_context
    with session_factory() as session:
        job_id, _second_job_id, candidate_id = seed_review_data(session)

    both_response = client.patch(
        f"/api/jobs/{job_id}/candidates/{candidate_id}/review",
        json={"status": "hired", "recruiter_notes": "Offer approved."},
    )
    invalid_response = client.patch(
        f"/api/jobs/{job_id}/candidates/{candidate_id}/review",
        json={"status": "maybe"},
    )

    assert both_response.status_code == 200
    assert both_response.json()["status"] == "hired"
    assert both_response.json()["recruiter_notes"] == "Offer approved."
    assert invalid_response.status_code == 422


def test_review_read_endpoint_and_job_review_list_are_ordered(review_context) -> None:
    client, session_factory = review_context
    with session_factory() as session:
        job_id, _second_job_id, candidate_id = seed_review_data(session)
        candidate_ids = [
            candidate.id
            for candidate in session.scalars(select(Candidate).order_by(Candidate.id)).all()
            if candidate.id != candidate_id
        ]

    review_response = client.get(f"/api/jobs/{job_id}/candidates/{candidate_id}/review")
    list_response = client.get(f"/api/jobs/{job_id}/reviews")

    assert review_response.status_code == 200
    assert review_response.json() == {
        "job_id": job_id,
        "candidate_id": candidate_id,
        "status": "reviewing",
        "recruiter_notes": "Initial review",
    }
    assert list_response.status_code == 200
    assert [item["candidate_id"] for item in list_response.json()] == [candidate_id, *candidate_ids]
    assert [item["match_score"] for item in list_response.json()] == [82.5, 61.0]


def test_reviews_are_isolated_per_job_and_scores_are_unchanged(review_context) -> None:
    client, session_factory = review_context
    with session_factory() as session:
        first_job_id, second_job_id, candidate_id = seed_review_data(session)

    response = client.patch(
        f"/api/jobs/{first_job_id}/candidates/{candidate_id}/review",
        json={"status": "rejected", "recruiter_notes": "Not a fit for this role."},
    )
    second_job_review = client.get(
        f"/api/jobs/{second_job_id}/candidates/{candidate_id}/review"
    )

    assert response.status_code == 200
    assert second_job_review.status_code == 200
    assert second_job_review.json()["status"] == "interview"
    assert second_job_review.json()["recruiter_notes"] == "Different job context"
    with session_factory() as session:
        associations = session.scalars(
            select(JobCandidate).where(JobCandidate.candidate_id == candidate_id)
        ).all()
        assert {(item.job_id, item.match_score) for item in associations} == {
            (first_job_id, 82.5),
            (second_job_id, 44.0),
        }


def test_review_errors_for_missing_resources_and_association(review_context) -> None:
    client, session_factory = review_context
    with session_factory() as session:
        job_id, _second_job_id, candidate_id = seed_review_data(session)
        unassociated = Candidate(name="Unassociated")
        session.add(unassociated)
        session.commit()
        session.refresh(unassociated)

    missing_job = client.get(f"/api/jobs/9999/candidates/{candidate_id}/review")
    missing_candidate = client.get(f"/api/jobs/{job_id}/candidates/9999/review")
    missing_association = client.get(
        f"/api/jobs/{job_id}/candidates/{unassociated.id}/review"
    )
    missing_list_job = client.get("/api/jobs/9999/reviews")

    assert missing_job.status_code == 404
    assert missing_candidate.status_code == 404
    assert missing_association.status_code == 404
    assert missing_list_job.status_code == 404


def test_review_routes_are_in_openapi(review_context) -> None:
    paths = review_context[0].get("/openapi.json").json()["paths"]

    assert "/api/jobs/{job_id}/candidates/{candidate_id}/review" in paths
    assert "/api/jobs/{job_id}/reviews" in paths
