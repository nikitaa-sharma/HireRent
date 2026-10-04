"""Grounded recruiter chat API route."""

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from app.database import get_db
from app.schemas.recruiter_chat import RecruiterChatRequest, RecruiterChatResponse
from app.services import llm_service
from app.services.recruiter_chat_service import answer_recruiter_message

router = APIRouter(prefix="/api/recruiter", tags=["Recruiter Chat"])


@router.post("/chat", response_model=RecruiterChatResponse)
def recruiter_chat(
    payload: RecruiterChatRequest, db: Session = Depends(get_db)
) -> RecruiterChatResponse:
    try:
        return answer_recruiter_message(db, payload.message, payload.job_id)
    except LookupError as error:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(error)) from error
    except llm_service.LLMNotConfiguredError as error:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(error)) from error
    except llm_service.LLMProviderError as error:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail="Recruiter chat provider is temporarily unavailable",
        ) from error
    except ValueError as error:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(error)) from error
