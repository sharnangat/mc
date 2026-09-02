import logging

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.chat import ChatMessage
from app.models.identity import User
from app.schemas.chat import ChatMessageOut, ChatRequest, ChatResponse, ChatSourceOut
from app.services.deps import get_current_user
from app.services.rag import draft_from_matches, retrieve_chunks

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/chat", tags=["chat"])

# Most recent turns to hand back when the chat page loads.
HISTORY_LIMIT = 50


@router.get("", response_model=list[ChatMessageOut])
async def list_chat_history(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Returns this user's most recent chat turns, oldest first."""
    result = await db.scalars(
        select(ChatMessage)
        .where(ChatMessage.user_id == user.id)
        .order_by(ChatMessage.created_at.desc())
        .limit(HISTORY_LIMIT)
    )
    messages = list(reversed(result.all()))
    return [
        ChatMessageOut(
            id=m.id,
            question=m.question,
            answer=ChatResponse(**m.answer_json),
            created_at=m.created_at,
        )
        for m in messages
    ]


@router.post("", response_model=ChatResponse)
async def chat(
    payload: ChatRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Ad hoc single-turn Q&A against the approved knowledge base.

    Reuses the exact same retrieval/drafting logic as the paid consultation
    pipeline (app/services/rag.py) so answers stay bound by the same
    guardrail: only what the retrieved matches actually say, otherwise
    insufficient_information. Each question/answer pair is saved to
    chat_messages (scoped to the asking user) so the chat page can restore
    history - this is a lighter-weight audit trail than the paid
    Query/AIAnswer pipeline, not a substitute for it.
    """
    message = payload.message.strip()
    if not message:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Message must not be empty")

    logger.info("Chat message from %s: %r", user.email, message[:100])
    matches = await retrieve_chunks(db, message)
    draft = draft_from_matches(matches)

    sources = [
        ChatSourceOut(
            document_id=document.id,
            document_title=document.title,
            page_number=chunk.page_number,
            relevance_score=max(0.0, 1 - distance / 2),
            cited_text=chunk.content_text[:500],
        )
        for chunk, document, distance in matches
    ]

    response = ChatResponse(
        technical_conclusion=draft["technical_conclusion"],
        technical_reasoning=draft["technical_reasoning"],
        recommended_action=draft["recommended_action"],
        insufficient_information=draft["insufficient_information"],
        sources=sources,
    )

    db.add(ChatMessage(user_id=user.id, question=message, answer_json=response.model_dump(mode="json")))
    await db.commit()

    return response
