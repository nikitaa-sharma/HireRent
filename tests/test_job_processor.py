from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.services.job_processor import process_job_description


@pytest.fixture
def processor_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'processor-test.db'}",
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


def test_basic_job_description_processing() -> None:
    result = process_job_description(
        "Senior Python Engineer",
        """
        Required: Python, FastAPI, PostgreSQL.
        Preferred: Docker and AWS.
        Minimum 5 years of experience. Bachelor's degree required.
        Location: Mumbai. Full-time.
        Responsibilities:
        - Build reliable backend services.
        - Review code and mentor engineers.
        """,
    )

    assert result.job_title == "Senior Python Engineer"
    assert result.required_skills == ["Python", "FastAPI", "PostgreSQL"]
    assert result.preferred_skills == ["Docker", "AWS"]
    assert result.required_experience_years == 5.0
    assert result.education == ["Bachelor's degree"]
    assert result.locations == ["Mumbai"]
    assert result.employment_type == "Full-time"
    assert result.responsibilities == [
        "Build reliable backend services.",
        "Review code and mentor engineers.",
    ]
    assert "Python" in result.keywords


def test_required_and_preferred_skill_context() -> None:
    result = process_job_description(
        "Frontend Developer",
        "Requirements: React and TypeScript are required. Nice to have: GraphQL.",
    )

    assert "React" in result.required_skills
    assert "TypeScript" in result.required_skills
    assert "GraphQL" in result.preferred_skills


def test_experience_uses_clearest_minimum_requirement() -> None:
    result = process_job_description(
        "Engineer",
        "At least 5 years of experience, including 3 years of Python experience.",
    )

    assert result.required_experience_years == 5.0


def test_other_supported_fields_are_extracted() -> None:
    result = process_job_description(
        "Data Analyst",
        "Master's degree or MBA. Based in Bengaluru. Contract role. 3+ years experience.",
    )

    assert result.education == ["Master's degree", "MBA"]
    assert result.locations == ["Bengaluru"]
    assert result.employment_type == "Contract"
    assert result.required_experience_years == 3.0


def test_empty_title_or_description_is_rejected() -> None:
    with pytest.raises(ValueError, match="Job title"):
        process_job_description("  ", "A description")
    with pytest.raises(ValueError, match="Job description"):
        process_job_description("Engineer", "  ")


def test_process_endpoint_returns_404_for_missing_job(processor_client: TestClient) -> None:
    response = processor_client.post("/api/jobs/9999/process")

    assert response.status_code == 404
    assert response.json()["detail"] == "Job not found"


def test_process_endpoint_processes_existing_job(processor_client: TestClient) -> None:
    create_response = processor_client.post(
        "/api/jobs",
        json={
            "title": "Backend Engineer",
            "description": "Python required. 3 years of experience. Full-time.",
        },
    )
    job_id = create_response.json()["id"]

    response = processor_client.post(f"/api/jobs/{job_id}/process")

    assert response.status_code == 200
    assert response.json()["job_title"] == "Backend Engineer"
    assert response.json()["required_skills"] == ["Python"]
    assert response.json()["required_experience_years"] == 3.0
    assert response.json()["employment_type"] == "Full-time"


def test_process_endpoint_is_in_openapi(processor_client: TestClient) -> None:
    openapi = processor_client.get("/openapi.json").json()

    assert "/api/jobs/{job_id}/process" in openapi["paths"]
