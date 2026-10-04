from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app


@pytest.fixture
def api_client(tmp_path) -> Generator[TestClient, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'api-test.db'}",
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


def create_job(client: TestClient) -> dict:
    response = client.post(
        "/api/jobs",
        json={"title": "AI Engineer", "description": "Python and FastAPI"},
    )
    assert response.status_code == 201
    return response.json()


def create_candidate(client: TestClient) -> dict:
    response = client.post(
        "/api/candidates",
        json={
            "name": "Rahul Sharma",
            "email": "rahul@example.com",
            "phone": "+91 1234567890",
            "location": "Mumbai",
        },
    )
    assert response.status_code == 201
    return response.json()


def test_create_job(api_client: TestClient) -> None:
    job = create_job(api_client)

    assert job["id"] > 0
    assert job["title"] == "AI Engineer"
    assert job["description"] == "Python and FastAPI"
    assert job["created_at"]
    assert job["updated_at"]


def test_list_and_get_jobs(api_client: TestClient) -> None:
    created_job = create_job(api_client)

    list_response = api_client.get("/api/jobs")
    get_response = api_client.get(f"/api/jobs/{created_job['id']}")

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == created_job["id"]
    assert get_response.status_code == 200
    assert get_response.json()["title"] == "AI Engineer"


def test_job_not_found_and_invalid_job_data(api_client: TestClient) -> None:
    missing_response = api_client.get("/api/jobs/9999")
    invalid_response = api_client.post(
        "/api/jobs", json={"title": "   ", "description": "Description"}
    )

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Job not found"
    assert invalid_response.status_code == 422


def test_create_candidate(api_client: TestClient) -> None:
    candidate = create_candidate(api_client)

    assert candidate["id"] > 0
    assert candidate["name"] == "Rahul Sharma"
    assert candidate["email"] == "rahul@example.com"


def test_list_and_get_candidates(api_client: TestClient) -> None:
    created_candidate = create_candidate(api_client)

    list_response = api_client.get("/api/candidates")
    get_response = api_client.get(f"/api/candidates/{created_candidate['id']}")

    assert list_response.status_code == 200
    assert list_response.json()[0]["id"] == created_candidate["id"]
    assert get_response.status_code == 200
    assert get_response.json()["location"] == "Mumbai"


def test_candidate_not_found_and_invalid_candidate_data(api_client: TestClient) -> None:
    missing_response = api_client.get("/api/candidates/9999")
    invalid_response = api_client.post(
        "/api/candidates", json={"name": "Candidate", "email": "not-an-email"}
    )

    assert missing_response.status_code == 404
    assert missing_response.json()["detail"] == "Candidate not found"
    assert invalid_response.status_code == 422


def test_associate_candidate_with_job(api_client: TestClient) -> None:
    job = create_job(api_client)
    candidate = create_candidate(api_client)

    response = api_client.post(f"/api/jobs/{job['id']}/candidates/{candidate['id']}")

    assert response.status_code == 201
    assert response.json()["job_id"] == job["id"]
    assert response.json()["candidate_id"] == candidate["id"]
    assert response.json()["status"] == "new"
    assert response.json()["candidate"]["name"] == "Rahul Sharma"


def test_list_candidates_for_job(api_client: TestClient) -> None:
    job = create_job(api_client)
    candidate = create_candidate(api_client)
    api_client.post(f"/api/jobs/{job['id']}/candidates/{candidate['id']}")

    response = api_client.get(f"/api/jobs/{job['id']}/candidates")

    assert response.status_code == 200
    assert response.json()[0]["candidate"]["id"] == candidate["id"]
    assert response.json()[0]["status"] == "new"


def test_association_requires_existing_job_and_candidate(api_client: TestClient) -> None:
    candidate = create_candidate(api_client)
    job = create_job(api_client)

    missing_job = api_client.post(f"/api/jobs/9999/candidates/{candidate['id']}")
    missing_candidate = api_client.post(f"/api/jobs/{job['id']}/candidates/9999")
    missing_job_candidates = api_client.get("/api/jobs/9999/candidates")

    assert missing_job.status_code == 404
    assert missing_job.json()["detail"] == "Job not found"
    assert missing_candidate.status_code == 404
    assert missing_candidate.json()["detail"] == "Candidate not found"
    assert missing_job_candidates.status_code == 404


def test_duplicate_association_returns_conflict(api_client: TestClient) -> None:
    job = create_job(api_client)
    candidate = create_candidate(api_client)
    endpoint = f"/api/jobs/{job['id']}/candidates/{candidate['id']}"

    first_response = api_client.post(endpoint)
    duplicate_response = api_client.post(endpoint)

    assert first_response.status_code == 201
    assert duplicate_response.status_code == 409
    assert duplicate_response.json()["detail"] == (
        "Candidate is already associated with this job"
    )


def test_openapi_docs_include_api_routes(api_client: TestClient) -> None:
    response = api_client.get("/openapi.json")

    assert response.status_code == 200
    assert "/api/jobs" in response.json()["paths"]
    assert "/api/candidates" in response.json()["paths"]
