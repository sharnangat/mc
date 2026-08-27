import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.consultation import AIAnswer, AIAnswerSource, ExpertReview, FinalAnswer, Query, QueryAttachment
from app.models.identity import User
from app.schemas.ai import AIAnswerOut
from app.schemas.query import AttachmentOut, QueryOut
from app.schemas.review import ExpertReviewCreate, ExpertReviewOut, FinalAnswerOut
from app.services.deps import require_roles
from app.services.rag import create_ai_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/expert", tags=["expert"])

REVIEW_QUEUE_STATUSES = ["draft_ready", "under_expert_review", "more_info_requested"]

require_expert = require_roles("expert", "admin", "superadmin")


async def _latest_ai_answer(db: AsyncSession, query_id: uuid.UUID) -> AIAnswer | None:
    stmt = (
        select(AIAnswer)
        .where(AIAnswer.query_id == query_id)
        .order_by(AIAnswer.created_at.desc())
        .limit(1)
    )
    return await db.scalar(stmt)


@router.get("/queries", response_model=list[QueryOut])
async def review_queue(user: User = Depends(require_expert), db: AsyncSession = Depends(get_db)):
    stmt = select(Query).where(Query.status.in_(REVIEW_QUEUE_STATUSES)).order_by(Query.created_at)
    result = await db.scalars(stmt)
    return result.all()


@router.get("/queries/{query_id}")
async def review_detail(query_id: uuid.UUID, user: User = Depends(require_expert), db: AsyncSession = Depends(get_db)):
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Query not found")

    ai_answer = await _latest_ai_answer(db, query_id)
    sources = []
    if ai_answer is not None:
        source_rows = (
            await db.scalars(select(AIAnswerSource).where(AIAnswerSource.ai_answer_id == ai_answer.id))
        ).all()
        sources = source_rows

    attachments = (
        await db.scalars(select(QueryAttachment).where(QueryAttachment.query_id == query_id))
    ).all()
    reviews = (
        await db.scalars(
            select(ExpertReview).where(ExpertReview.query_id == query_id).order_by(ExpertReview.created_at)
        )
    ).all()

    ai_answer_out = None
    if ai_answer is not None:
        ai_answer_out = AIAnswerOut.model_validate(ai_answer)
        ai_answer_out.sources = [
            {
                "id": s.id,
                "document_id": s.document_id,
                "relevance_score": s.relevance_score,
                "cited_text": s.cited_text,
                "page_number": s.page_number,
                "section": s.section,
                "clause_number": s.clause_number,
            }
            for s in sources
        ]

    return {
        "query": QueryOut.model_validate(query),
        "attachments": [AttachmentOut.model_validate(a) for a in attachments],
        "ai_answer": ai_answer_out,
        "reviews": [ExpertReviewOut.model_validate(r) for r in reviews],
    }


@router.post("/queries/{query_id}/review", response_model=ExpertReviewOut)
async def submit_review(
    query_id: uuid.UUID,
    payload: ExpertReviewCreate,
    user: User = Depends(require_expert),
    db: AsyncSession = Depends(get_db),
):
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Query not found")

    ai_answer = await _latest_ai_answer(db, query_id)

    review = ExpertReview(
        query_id=query_id,
        ai_answer_id=ai_answer.id if ai_answer else None,
        expert_id=user.id,
        action=payload.action,
        edited_technical_conclusion=payload.edited_technical_conclusion,
        edited_technical_reasoning=payload.edited_technical_reasoning,
        edited_recommended_action=payload.edited_recommended_action,
        comment=payload.comment,
    )
    db.add(review)
    await db.flush()

    if payload.action == "approve":
        if ai_answer is None:
            raise HTTPException(status.HTTP_409_CONFLICT, detail="No AI draft to approve")
        conclusion = payload.edited_technical_conclusion or ai_answer.technical_conclusion
        reasoning = payload.edited_technical_reasoning or ai_answer.technical_reasoning
        action_text = payload.edited_recommended_action or ai_answer.recommended_action

        sources = (
            await db.scalars(select(AIAnswerSource).where(AIAnswerSource.ai_answer_id == ai_answer.id))
        ).all()
        references = [
            {"document_id": str(s.document_id), "cited_text": s.cited_text, "page_number": s.page_number}
            for s in sources
        ]

        db.add(
            FinalAnswer(
                query_id=query_id,
                expert_review_id=review.id,
                approved_by=user.id,
                final_technical_conclusion=conclusion,
                final_technical_reasoning=reasoning,
                final_recommended_action=action_text,
                references_json=references,
            )
        )
        query.status = "approved"
    elif payload.action == "reject":
        query.status = "rejected"
    elif payload.action == "request_more_info":
        query.status = "more_info_requested"
    elif payload.action == "rerun_analysis":
        query.status = "ai_processing"
        await db.flush()
        await create_ai_answer(db, query)
    elif payload.action in ("edit", "comment"):
        query.status = "under_expert_review"
        query.assigned_expert_id = user.id

    await db.commit()
    await db.refresh(review)
    logger.info("Expert %s: action=%s on query %s -> status=%s", user.email, payload.action, query_id, query.status)
    return review


@router.post("/queries/{query_id}/send", response_model=FinalAnswerOut)
async def send_to_customer(
    query_id: uuid.UUID,
    user: User = Depends(require_expert),
    db: AsyncSession = Depends(get_db),
):
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Query not found")

    final_answer = await db.scalar(select(FinalAnswer).where(FinalAnswer.query_id == query_id))
    if final_answer is None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail="Query has not been approved yet")

    final_answer.sent_at = datetime.now(timezone.utc)
    final_answer.sent_via = ["website"]
    query.status = "sent"

    await db.commit()
    await db.refresh(final_answer)
    logger.info("Final answer sent to customer for query %s by %s", query_id, user.email)
    return final_answer
