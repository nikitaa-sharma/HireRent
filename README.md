# Hirent

Hirent is an AI-powered recruitment intelligence and decision-support platform for recruiters. It helps recruiters discover, search, evaluate, and compare candidates while keeping final hiring decisions with people. Hirent is human-in-the-loop: it provides evidence and workflow support, but never makes or applies an automatic hiring decision.

## Current status

The application includes a FastAPI backend and Streamlit recruiter dashboard for job creation, resume uploads, processing, indexing, matching, evidence-backed explanations, semantic search, comparison, recruiter review, and grounded recruiter chat.

### Architecture

The FastAPI backend exposes the recruiter workflow APIs and uses SQLAlchemy with local SQLite for application data. Job and candidate processing uses local `sentence-transformers` embeddings with FAISS for vector search. The Streamlit frontend calls the backend through `BACKEND_URL`; it does not access SQLite, FAISS, or the optional LLM provider directly.

## Setup

Python 3.11 or newer is recommended.

### Create a virtual environment

Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
```

macOS/Linux:

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### Install dependencies

```bash
python -m pip install --upgrade pip
pip install -r requirements.txt
```

### Configure environment variables

Copy `.env.example` to `.env` and adjust values if needed. The defaults use a local SQLite database and the `uploads/` directory. `BACKEND_URL` defaults to `http://127.0.0.1:8000`. LLM settings are optional and are only needed for Recruiter Chat. Do not commit `.env` or real secrets.

### Run the FastAPI backend

```bash
uvicorn app.main:app --reload
```

The health check is available at `http://127.0.0.1:8000/health`.

### Upload PDF resumes

Resumes can be uploaded as PDFs through `POST /api/candidates/upload-resume`. Hirent extracts the PDF text and stores it with the candidate record. The maximum upload size is controlled by `MAX_UPLOAD_SIZE_MB` in the environment configuration.

Job descriptions can be processed locally through `POST /api/jobs/{job_id}/process` to produce structured requirements using a deterministic rule-based processor.

Hirent uses local `sentence-transformers` embeddings and FAISS for semantic vector search. This layer does not require an external API.

Hirent can calculate a job-specific candidate match score using local semantic similarity and structured requirement compatibility. The score is decision support only and does not automatically make a hiring decision.

Hirent also provides evidence-backed match explanations using relevant excerpts from the job description and candidate resume. These explanations support recruiter review; the recruiter remains responsible for the hiring decision.

Recruiters can search indexed candidates with natural-language queries through `GET /api/candidates/search`, with optional skill, minimum-experience, and location filters.

Recruiters can compare 2 to 5 associated candidates side by side for a job through `GET /api/jobs/{job_id}/compare`, including existing scores, components, strengths, gaps, and evidence.

Recruiters can track job-specific candidate status and private recruiter notes through the review endpoints.

Grounded recruiter chat is available through `POST /api/recruiter/chat` and the Streamlit Recruiter Chat page. It answers from retrieved Hirent records and evidence as recruiter decision support; it does not make an automated hiring decision. Chat history is session-only in the frontend and is not persisted. Configure an LLM provider only when chat is needed.

The Hirent Streamlit recruiter dashboard is available through `streamlit run frontend/app.py`. It connects to the existing FastAPI backend using `BACKEND_URL` (default: `http://127.0.0.1:8000`) and provides job creation, candidate uploads, processing/indexing controls, backend-generated matching, semantic candidate search, candidate comparison, recruiter review statuses, private recruiter notes, match scores, evidence, and review-status views. Matching, search, comparison, and review statuses remain recruiter-controlled decision support; the recruiter remains responsible for hiring decisions.

### Run the Streamlit frontend

In a second terminal with the virtual environment activated:

```bash
streamlit run frontend/app.py
```

### Run tests

```bash
python -m pytest
```
