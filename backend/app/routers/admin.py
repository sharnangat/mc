import asyncio
import logging
import uuid

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.catalog import PricingPlan
from app.models.consultation import Payment, Query
from app.models.identity import User
from app.models.knowledge import KnowledgeDocument
from app.schemas.admin import DocumentType, KnowledgeDocumentOut, KnowledgeDocumentUpdate
from app.schemas.catalog import PricingPlanOut, PricingPlanUpdate
from app.schemas.payment import PaymentOut
from app.schemas.query import QueryOut
from app.services.deps import require_roles
from app.services.ingest_pipeline import run_document_ingest
from app.services.storage import save_upload

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/admin", tags=["admin"])

require_admin = require_roles("admin", "superadmin")


@router.post("/documents", response_model=KnowledgeDocumentOut, status_code=status.HTTP_201_CREATED)
async def upload_document(
    title: str = Form(...),
    document_type: DocumentType = Form(...),
    standard_name: str | None = Form(None),
    edition_year: int | None = Form(None),
    revision: str | None = Form(None),
    source_owner: str | None = Form(None),
    licence_status: str = Form("unlicensed"),
    access_permission: str = Form("restricted"),
    file: UploadFile = File(...),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stored_path, _ = await save_upload(file, subdir="documents")
    document = KnowledgeDocument(
        title=title,
        document_type=document_type,
        standard_name=standard_name,
        edition_year=edition_year,
        revision=revision,
        source_owner=source_owner,
        licence_status=licence_status,
        access_permission=access_permission,
        file_path=stored_path,
        uploaded_by=user.id,
        is_enabled_for_ai=False,
        indexing_status="pending",
    )
    db.add(document)
    await db.commit()
    await db.refresh(document)
    logger.info("Document uploaded: %s (%s) by %s", document.title, document.id, user.email)
    return document


@router.get("/documents", response_model=list[KnowledgeDocumentOut])
async def list_documents(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(KnowledgeDocument).order_by(KnowledgeDocument.uploaded_at.desc()))
    return result.all()


@router.patch("/documents/{document_id}", response_model=KnowledgeDocumentOut)
async def update_document(
    document_id: uuid.UUID,
    payload: KnowledgeDocumentUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")

    changes = payload.model_dump(exclude_unset=True)
    for field, value in changes.items():
        setattr(document, field, value)

    await db.commit()
    await db.refresh(document)
    if "is_enabled_for_ai" in changes:
        logger.info(
            "Document %s (%s) AI-enabled=%s by %s",
            document.title,
            document.id,
            document.is_enabled_for_ai,
            user.email,
        )
    return document


@router.delete("/documents/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_document(document_id: uuid.UUID, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")
    await db.delete(document)
    await db.commit()
    logger.info("Document deleted: %s (%s) by %s", document.title, document.id, user.email)


@router.post("/documents/{document_id}/ingest", response_model=KnowledgeDocumentOut)
async def ingest_document(
    document_id: uuid.UUID,
    content_text: str | None = Form(
        None, description="Extracted plain text of the document. Omit to auto-extract from the stored file (PDF/TXT)."
    ),
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    document = await db.get(KnowledgeDocument, document_id)
    if document is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Document not found")

    logger.info("Ingest started for %s (%s), source=%s", document.title, document.id, "pasted text" if content_text else "file")

    try:
        total = await asyncio.to_thread(
            run_document_ingest,
            document.id,
            document.file_path,
            content_text,
        )
    except FileNotFoundError as exc:
        logger.warning("Ingest failed for %s (%s): %s", document.title, document.id, exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except ValueError as exc:
        logger.warning("Ingest failed for %s (%s): %s", document.title, document.id, exc)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except Exception as exc:
        logger.exception("Ingest failed for %s (%s)", document.title, document.id)
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Ingestion failed while processing the document. Check server logs for details.",
        ) from exc

    await db.refresh(document)
    logger.info("Ingest completed for %s (%s): %d chunks indexed", document.title, document.id, total)
    return document


@router.get("/queries", response_model=list[QueryOut])
async def list_all_queries(
    status_filter: str | None = None,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Query).order_by(Query.created_at.desc())
    if status_filter:
        stmt = stmt.where(Query.status == status_filter)
    result = await db.scalars(stmt)
    return result.all()


@router.get("/payments", response_model=list[PaymentOut])
async def list_payments(user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.scalars(select(Payment).order_by(Payment.created_at.desc()))
    return result.all()


@router.patch("/pricing-plans/{plan_id}", response_model=PricingPlanOut)
async def update_pricing_plan(
    plan_id: uuid.UUID,
    payload: PricingPlanUpdate,
    user: User = Depends(require_admin),
    db: AsyncSession = Depends(get_db),
):
    plan = await db.get(PricingPlan, plan_id)
    if plan is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Pricing plan not found")

    for field, value in payload.model_dump(exclude_unset=True).items():
        setattr(plan, field, value)

    await db.commit()
    await db.refresh(plan)
    return plan
