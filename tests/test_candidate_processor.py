from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.services.candidate_processor import process_candidate_resume


RESUME_TEXT = """Summary:
Backend engineer building reliable services and data platforms.

Skills:
Python, FastAPI, PostgreSQL, Docker, AWS

Experience:
Senior Software Engineer | Acme Corp | 2020 - 2024
Backend Developer at Beta Labs | 2018 - 2020
Worked for 5 years building APIs and data systems.

Education:
B.Tech in Computer Science, State University

Certifications:
AWS Certified Solutions Architect
Certified Kubernetes Administrator
"""


@pytest.fixture
def candidate_processor_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'candidate-processor-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_basic_candidate_processing() -> None:
    profile = process_candidate_resume(
        candidate_id=7,
        name="Rahul Sharma",
        email="rahul@example.com",
        phone="12345",
        location="Mumbai",
        resume_text=RESUME_TEXT,
    )

    assert profile.candidate_id == 7
    assert profile.name == "Rahul Sharma"
    assert profile.email == "rahul@example.com"
    assert profile.location == "Mumbai"
    assert "Python" in profile.skills
    assert "FastAPI" in profile.skills
    assert profile.experience_years == 5.0
    assert profile.education == ["B.Tech in Computer Science, State University"]
    assert profile.companies == ["Acme Corp", "Beta Labs"]
    assert profile.job_titles == ["Senior Software Engineer", "Backend Developer"]
    assert "AWS Certified Solutions Architect" in profile.certifications
    assert profile.summary == "Backend engineer building reliable services and data platforms."
    assert "Python" in profile.keywords
    assert "Senior Software Engineer" in profile.keywords


def test_skill_extraction_is_case_insensitive_and_canonical() -> None:
    profile = process_candidate_resume(
        None, "Candidate", None, None, None, "SKILLS: python, FASTAPI, postgresql, Docker"
    )

    assert profile.skills == ["Python", "FastAPI", "PostgreSQL", "Docker"]


def test_experience_does_not_infer_from_job_count() -> None:
    profile = process_candidate_resume(
        None,
        "Candidate",
        None,
        None,
        None,
        "Experience:\nSoftware Engineer | Example Corp\nBackend Developer | Other Corp",
    )

    assert profile.experience_years is None


def test_empty_resume_validation() -> None:
    with pytest.raises(ValueError, match="Resume text"):
        process_candidate_resume(None, "Candidate", None, None, None, "  ")


def test_missing_candidate_returns_404(candidate_processor_client: TestClient) -> None:
    response = candidate_processor_client.post("/api/candidates/9999/process")

    assert response.status_code == 404
    assert response.json()["detail"] == "Candidate not found"


def test_candidate_without_resume_returns_400(candidate_processor_client: TestClient) -> None:
    create_response = candidate_processor_client.post(
        "/api/candidates", json={"name": "Candidate"}
    )

    response = candidate_processor_client.post(
        f"/api/candidates/{create_response.json()['id']}/process"
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Candidate does not have stored resume text"


def test_successful_processing_endpoint(candidate_processor_client: TestClient) -> None:
    create_response = candidate_processor_client.post(
        "/api/candidates",
        json={
            "name": "Rahul Sharma",
            "email": "rahul@example.com",
            "location": "Mumbai",
        },
    )
    candidate_id = create_response.json()["id"]

    from app.models import Candidate

    with candidate_processor_client as client:
        session_factory = app.dependency_overrides[get_db]
        assert session_factory is not None
        # The endpoint test uses the API path; resume text is seeded through the test database.
        session = next(session_factory())
        candidate = session.get(Candidate, candidate_id)
        assert candidate is not None
        candidate.resume_text = RESUME_TEXT
        session.commit()
        session.close()
        response = client.post(f"/api/candidates/{candidate_id}/process")

    assert response.status_code == 200
    assert response.json()["candidate_id"] == candidate_id
    assert response.json()["skills"][:2] == ["Python", "FastAPI"]
    assert response.json()["companies"] == ["Acme Corp", "Beta Labs"]


def test_processing_route_is_in_openapi(candidate_processor_client: TestClient) -> None:
    openapi = candidate_processor_client.get("/openapi.json").json()

    assert "/api/candidates/{candidate_id}/process" in openapi["paths"]
