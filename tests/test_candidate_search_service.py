from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base, get_db
from app.main import app
from app.models import Candidate
from app.services import vector_store
from app.services.candidate_search_service import search_candidates


@pytest.fixture
def search_context(tmp_path, monkeypatch) -> Generator[tuple[Session, TestClient], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'search-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    monkeypatch.setattr(
        vector_store,
        "search_candidates",
        lambda query, limit=10: [
            {"entity_type": "candidate", "entity_id": 2, "score": 0.95},
            {"entity_type": "candidate", "entity_id": 1, "score": 0.75},
            {"entity_type": "candidate", "entity_id": 999, "score": 0.99},
        ][:limit],
    )
    with test_session() as session:
        yield session, TestClient(app)

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def seed_candidates(session: Session) -> None:
    session.add_all(
        [
            Candidate(
                id=1,
                name="First Candidate",
                email="first@example.com",
                location="Delhi",
                resume_text="Skills: Python\nExperience: 2 years of experience",
            ),
            Candidate(
                id=2,
                name="Second Candidate",
                email="second@example.com",
                location="Mumbai",
                resume_text="Python backend engineer with AWS and Docker. 5 years of experience.",
            ),
        ]
    )
    session.commit()


def test_basic_search_hydrates_candidates_and_preserves_order(search_context) -> None:
    session, _client = search_context
    seed_candidates(session)

    results = search_candidates(session, "Python backend developer", limit=10)

    assert [result.candidate_id for result in results] == [2, 1]
    assert results[0].name == "Second Candidate"
    assert results[0].similarity_score == 97.5
    assert "AWS" in (results[0].evidence or "")
    assert all(result.candidate_id != 999 for result in results)


def test_limit_validation_and_empty_results(search_context, monkeypatch) -> None:
    session, _client = search_context
    seed_candidates(session)

    with pytest.raises(ValueError, match="between 1 and 100"):
        search_candidates(session, "engineer", limit=0)
    with pytest.raises(ValueError, match="must not be empty"):
        search_candidates(session, " ")

    monkeypatch.setattr(vector_store, "search_candidates", lambda query, limit=10: [])
    assert search_candidates(session, "no match") == []


def test_explicit_skill_experience_and_location_filters(search_context) -> None:
    session, _client = search_context
    seed_candidates(session)

    results = search_candidates(
        session,
        "senior engineer with AWS and Docker",
        required_skills=["AWS", "Docker"],
        min_experience_years=3,
        location="Mumbai",
    )

    assert [result.candidate_id for result in results] == [2]


def test_search_does_not_mutate_candidates(search_context) -> None:
    session, _client = search_context
    seed_candidates(session)
    before = session.scalar(select(Candidate).where(Candidate.id == 2))
    assert before is not None
    before_values = (before.name, before.email, before.location, before.resume_text)

    search_candidates(session, "Python")
    session.expire_all()
    after = session.scalar(select(Candidate).where(Candidate.id == 2))

    assert after is not None
    assert (after.name, after.email, after.location, after.resume_text) == before_values


def test_search_api_supports_filters_and_stale_ids_are_ignored(search_context) -> None:
    session, client = search_context
    seed_candidates(session)

    response = client.get(
        "/api/candidates/search",
        params={
            "q": "Python backend developer",
            "limit": 5,
            "skills": "AWS",
            "min_experience_years": 3,
            "location": "Mumbai",
        },
    )

    assert response.status_code == 200
    assert [result["candidate_id"] for result in response.json()["results"]] == [2]
    assert response.json()["results"][0]["entity_id"] == 2


def test_empty_search_query_returns_400(search_context) -> None:
    _session, client = search_context

    response = client.get("/api/candidates/search", params={"q": " "})

    assert response.status_code == 400
