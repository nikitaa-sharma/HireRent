from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.services import vector_store


@pytest.fixture
def vector_api_client(tmp_path, monkeypatch) -> Generator[TestClient, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'vector-api-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    monkeypatch.setattr(vector_store, "index_candidate", lambda candidate_id, text: None)
    monkeypatch.setattr(vector_store, "index_job", lambda job_id, text: None)
    monkeypatch.setattr(
        vector_store,
        "search_candidates",
        lambda query, limit: [{"entity_type": "candidate", "entity_id": 1, "score": 0.95}],
    )

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    yield TestClient(app)
    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def test_candidate_indexing(vector_api_client: TestClient) -> None:
    create_response = vector_api_client.post(
        "/api/candidates",
        json={"name": "Candidate", "location": "Mumbai"},
    )

    response = vector_api_client.post(
        f"/api/candidates/{create_response.json()['id']}/index"
    )

    assert response.status_code == 400


def test_candidate_indexing_with_resume(vector_api_client: TestClient) -> None:
    create_response = vector_api_client.post(
        "/api/candidates", json={"name": "Candidate"}
    )
    candidate_id = create_response.json()["id"]
    from app.models import Candidate

    session = next(app.dependency_overrides[get_db]())
    candidate = session.get(Candidate, candidate_id)
    candidate.resume_text = "Python backend engineer"
    session.commit()
    session.close()

    response = vector_api_client.post(f"/api/candidates/{candidate_id}/index")

    assert response.status_code == 200
    assert response.json() == {"candidate_id": candidate_id, "status": "indexed"}


def test_job_indexing_and_missing_resources(vector_api_client: TestClient) -> None:
    missing_job = vector_api_client.post("/api/jobs/9999/index")
    create_response = vector_api_client.post(
        "/api/jobs", json={"title": "Engineer", "description": "Python"}
    )
    job_id = create_response.json()["id"]
    indexed_job = vector_api_client.post(f"/api/jobs/{job_id}/index")

    assert missing_job.status_code == 404
    assert indexed_job.status_code == 200
    assert indexed_job.json() == {"job_id": job_id, "status": "indexed"}


def test_search_candidates_and_empty_query(vector_api_client: TestClient) -> None:
    create_response = vector_api_client.post(
        "/api/candidates", json={"name": "Indexed Candidate"}
    )
    assert create_response.status_code == 201

    response = vector_api_client.get("/api/candidates/search?q=python&limit=5")
    empty_response = vector_api_client.get("/api/candidates/search?q= ")

    assert response.status_code == 200
    assert response.json()["results"][0]["entity_id"] == 1
    assert empty_response.status_code == 400


def test_vector_routes_are_in_openapi(vector_api_client: TestClient) -> None:
    paths = vector_api_client.get("/openapi.json").json()["paths"]

    assert "/api/candidates/{candidate_id}/index" in paths
    assert "/api/jobs/{job_id}/index" in paths
    assert "/api/candidates/search" in paths
