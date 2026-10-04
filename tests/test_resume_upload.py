from collections.abc import Generator
from pathlib import Path

import fitz
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, select
from sqlalchemy.orm import Session, sessionmaker

import app.api.candidates as candidate_api
from app.database import Base, get_db
from app.main import app
from app.models import Candidate


@pytest.fixture
def upload_context(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> Generator[tuple[TestClient, Session, Path], None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'resume-test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    upload_dir = tmp_path / "uploads"
    monkeypatch.setattr(candidate_api, "UPLOAD_DIR", upload_dir)

    def override_get_db() -> Generator[Session, None, None]:
        with test_session() as session:
            yield session

    app.dependency_overrides[get_db] = override_get_db
    with test_session() as session:
        yield TestClient(app), session, upload_dir

    app.dependency_overrides.clear()
    Base.metadata.drop_all(bind=engine)
    engine.dispose()


def make_pdf(text: str | None = "Experienced Python developer") -> bytes:
    document = fitz.open()
    page = document.new_page()
    if text:
        page.insert_text((72, 72), text)
    pdf_bytes = document.tobytes()
    document.close()
    return pdf_bytes


def upload_pdf(client: TestClient, content: bytes, filename: str = "resume.pdf"):
    return client.post(
        "/api/candidates/upload-resume",
        files={"file": (filename, content, "application/pdf")},
    )


def test_successful_upload_extracts_text_and_saves_metadata(upload_context) -> None:
    client, session, upload_dir = upload_context

    response = client.post(
        "/api/candidates/upload-resume",
        files={"file": ("candidate.pdf", make_pdf(), "application/pdf")},
        data={
            "name": "Rahul Sharma",
            "email": "rahul@example.com",
            "phone": "+91 1234567890",
            "location": "Mumbai",
        },
    )

    assert response.status_code == 201
    candidate = response.json()
    stored_candidate = session.scalar(select(Candidate).where(Candidate.id == candidate["id"]))
    saved_files = list(upload_dir.iterdir())

    assert candidate["name"] == "Rahul Sharma"
    assert candidate["email"] == "rahul@example.com"
    assert candidate["phone"] == "+91 1234567890"
    assert candidate["location"] == "Mumbai"
    assert candidate["resume_filename"] == saved_files[0].name
    assert candidate["resume_text"] == "Experienced Python developer"
    assert stored_candidate is not None
    assert stored_candidate.resume_text == "Experienced Python developer"
    assert "/" not in candidate["resume_filename"]
    assert "\\" not in candidate["resume_filename"]


def test_upload_filenames_are_safe_and_unique(upload_context) -> None:
    client, _session, upload_dir = upload_context

    first_response = upload_pdf(client, make_pdf("First resume"), "same-name.pdf")
    second_response = upload_pdf(client, make_pdf("Second resume"), "same-name.pdf")

    assert first_response.status_code == 201
    assert second_response.status_code == 201
    first_filename = first_response.json()["resume_filename"]
    second_filename = second_response.json()["resume_filename"]
    assert first_filename != second_filename
    assert first_filename.endswith(".pdf")
    assert second_filename.endswith(".pdf")
    assert {path.name for path in upload_dir.iterdir()} == {first_filename, second_filename}


def test_non_pdf_upload_returns_400(upload_context) -> None:
    client, _session, upload_dir = upload_context

    response = client.post(
        "/api/candidates/upload-resume",
        files={"file": ("resume.txt", b"plain text", "text/plain")},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Only PDF resume files are accepted"
    assert not upload_dir.exists()


def test_oversized_upload_returns_413_and_cleans_up(upload_context, monkeypatch) -> None:
    client, _session, upload_dir = upload_context
    monkeypatch.setattr("app.api.candidates.MAX_UPLOAD_SIZE_MB", 0)

    response = upload_pdf(client, make_pdf())

    assert response.status_code == 413
    assert not list(upload_dir.iterdir())


def test_empty_text_pdf_returns_400_and_cleans_up(upload_context) -> None:
    client, _session, upload_dir = upload_context

    response = upload_pdf(client, make_pdf(None))

    assert response.status_code == 400
    assert response.json()["detail"] == "The PDF does not contain meaningful text"
    assert not list(upload_dir.iterdir())


def test_invalid_pdf_returns_400_and_cleans_up(upload_context) -> None:
    client, _session, upload_dir = upload_context

    response = upload_pdf(client, b"not a real PDF")

    assert response.status_code == 400
    assert response.json()["detail"] == "Unable to read the PDF file"
    assert not list(upload_dir.iterdir())
