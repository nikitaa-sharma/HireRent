from collections.abc import Generator

import pytest
from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import Session, sessionmaker

from app.database import Base
from app.models import Candidate, Job, JobCandidate


@pytest.fixture
def db_session(tmp_path) -> Generator[Session, None, None]:
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(bind=engine)
    test_session = sessionmaker(bind=engine, autoflush=False, autocommit=False)

    with test_session() as session:
        yield session

    Base.metadata.drop_all(bind=engine)


def test_database_tables_can_be_created(db_session: Session) -> None:
    table_names = inspect(db_session.bind).get_table_names()

    assert {"jobs", "candidates", "job_candidates"}.issubset(table_names)


def test_job_can_be_inserted_and_retrieved(db_session: Session) -> None:
    job = Job(title="Backend Engineer", description="Build APIs")
    db_session.add(job)
    db_session.commit()

    retrieved_job = db_session.get(Job, job.id)

    assert retrieved_job is not None
    assert retrieved_job.title == "Backend Engineer"
    assert retrieved_job.description == "Build APIs"
    assert retrieved_job.created_at is not None
    assert retrieved_job.updated_at is not None


def test_candidate_can_be_inserted_and_retrieved(db_session: Session) -> None:
    candidate = Candidate(
        name="Jordan Lee",
        email="jordan@example.com",
        location="Remote",
        resume_filename="jordan-lee.pdf",
        resume_text="Python and FastAPI experience",
    )
    db_session.add(candidate)
    db_session.commit()

    retrieved_candidate = db_session.get(Candidate, candidate.id)

    assert retrieved_candidate is not None
    assert retrieved_candidate.name == "Jordan Lee"
    assert retrieved_candidate.email == "jordan@example.com"
    assert retrieved_candidate.resume_text == "Python and FastAPI experience"


def test_job_candidate_stores_relationship_data(db_session: Session) -> None:
    job = Job(title="Data Engineer", description="Build data systems")
    candidate = Candidate(name="Sam Rivera")
    association = JobCandidate(
        job=job,
        candidate=candidate,
        match_score=0.91,
        status="reviewed",
        recruiter_notes="Strong SQL background",
    )
    db_session.add(association)
    db_session.commit()
    db_session.refresh(association)

    assert association.job.id == job.id
    assert association.candidate.id == candidate.id
    assert association.match_score == 0.91
    assert association.status == "reviewed"
    assert association.recruiter_notes == "Strong SQL background"
    assert job.job_candidates == [association]
    assert candidate.job_candidates == [association]
    assert job.candidates == [candidate]
    assert candidate.jobs == [job]


def test_candidate_can_be_associated_with_multiple_jobs(db_session: Session) -> None:
    candidate = Candidate(name="Taylor Morgan")
    first_job = Job(title="Platform Engineer", description="Own platform services")
    second_job = Job(title="API Engineer", description="Build public APIs")
    candidate.job_candidates.extend(
        [
            JobCandidate(job=first_job),
            JobCandidate(job=second_job, status="shortlisted"),
        ]
    )
    db_session.add(candidate)
    db_session.commit()

    db_session.refresh(candidate)

    assert len(candidate.job_candidates) == 2
    assert {association.job.title for association in candidate.job_candidates} == {
        "Platform Engineer",
        "API Engineer",
    }
    assert {job.title for job in candidate.jobs} == {"Platform Engineer", "API Engineer"}
