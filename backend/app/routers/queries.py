import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.consultation import FinalAnswer, Query, QueryAttachment
from app.models.identity import User
from app.schemas.query import AttachmentType, QueryCreate, QueryDetailOut, QueryOut
from app.schemas.review import FinalAnswerOut
from app.services.deps import get_current_user
from app.services.storage import save_upload

router = APIRouter(prefix="/queries", tags=["queries"])

STAFF_ROLES = {"expert", "admin", "superadmin"}


def _user_role_codes(user: User) -> set[str]:
    return {ur.role.code for ur in user.roles}


def _ensure_query_access(query: Query, user: User) -> None:
    if query.customer_id == user.id:
        return
    if _user_role_codes(user) & STAFF_ROLES:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not authorized to view this query")


@router.post("", response_model=QueryOut, status_code=status.HTTP_201_CREATED)
async def create_query(
    payload: QueryCreate,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = Query(
        customer_id=user.id,
        consultation_category_id=payload.consultation_category_id,
        pricing_plan_id=payload.pricing_plan_id,
        question_text=payload.question_text,
        priority=payload.priority,
    )
    db.add(query)
    await db.commit()
    await db.refresh(query)
    return query


@router.get("", response_model=list[QueryOut])
async def list_queries(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    stmt = select(Query).order_by(Query.created_at.desc())
    if not (_user_role_codes(user) & STAFF_ROLES):
        stmt = stmt.where(Query.customer_id == user.id)
    result = await db.scalars(stmt)
    return result.all()


@router.get("/{query_id}", response_model=QueryDetailOut)
async def get_query(query_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Query not found")
    _ensure_query_access(query, user)

    attachments = (
        await db.scalars(select(QueryAttachment).where(QueryAttachment.query_id == query_id))
    ).all()
    result = QueryDetailOut.model_validate(query)
    result.attachments = list(attachments)

    if query.status == "sent":
        final_answer = await db.scalar(select(FinalAnswer).where(FinalAnswer.query_id == query_id))
        if final_answer is not None:
            result.final_answer = FinalAnswerOut.model_validate(final_answer)

    return result


@router.post("/{query_id}/attachments", status_code=status.HTTP_201_CREATED)
async def upload_attachment(
    query_id: uuid.UUID,
    attachment_type: AttachmentType = Form(...),
    file: UploadFile = File(...),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Query not found")
    _ensure_query_access(query, user)

    stored_path, original_name = await save_upload(file, subdir=f"queries/{query_id}")
    attachment = QueryAttachment(
        query_id=query_id,
        attachment_type=attachment_type,
        file_name=original_name,
        file_path=stored_path,
        uploaded_by=user.id,
    )
    db.add(attachment)
    await db.commit()
    await db.refresh(attachment)
    return {"id": attachment.id, "file_name": attachment.file_name}
