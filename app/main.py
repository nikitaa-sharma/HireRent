"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import APP_NAME
from app.database import init_db
from app.api.candidates import router as candidates_router
from app.api.jobs import router as jobs_router
from app.api.recruiter_chat import router as recruiter_chat_router


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
    """Initialize database tables when the application starts."""

    init_db()
    yield


app = FastAPI(title=APP_NAME, lifespan=lifespan)
app.include_router(jobs_router)
app.include_router(candidates_router)
app.include_router(recruiter_chat_router)


@app.get("/health")
def health_check() -> dict[str, str]:
    """Return a lightweight service health response."""

    return {"status": "ok", "service": APP_NAME}
