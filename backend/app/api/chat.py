from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from backend.app.database import get_db
from backend.app.models import SessionModel
from backend.app.schemas import ChatRequest, ChatResponse
from backend.app.services.llm.chat_agent import chat_agent_service

router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/{session_id}", response_model=ChatResponse)
async def chat_with_session_agent(
    session_id: str,
    req: ChatRequest,
    db: AsyncSession = Depends(get_db)
):
    """
    Interactive Q&A chat endpoint with an AI agent equipped with tools
    to search the entire transcription and pedagogical report.
    """
    session = await db.get(SessionModel, session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")

    response = await chat_agent_service.chat(
        session_id=session_id,
        user_message=req.message,
        history=req.history,
        db=db,
        openrouter_api_key=req.openrouter_api_key,
        openrouter_model=req.openrouter_model
    )

    return response
