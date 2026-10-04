from __future__ import annotations

import gc
import logging
import uuid
from collections.abc import Iterator
from datetime import datetime, timezone

from sqlalchemy import create_engine, delete, text, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models.knowledge import DocumentChunk, KnowledgeDocument
from app.services.ingestion import (
    MIN_CHUNK_WORDS,
    build_chunk_records,
    build_chunk_records_from_pages_batch,
)
from app.services.pdf_extraction import iter_document_pages

logger = logging.getLogger(__name__)

# Small batches keep peak RAM low on 1GB droplets (PDF extract + embeddings + ORM).
PAGE_BATCH_SIZE = 4
EMBED_BATCH_SIZE = 8


def _sync_engine():
    sync_url = settings.database_url.replace("postgresql+asyncpg://", "postgresql+psycopg2://")
    return create_engine(
        sync_url,
        pool_pre_ping=True,
        connect_args={"options": f"-csearch_path={settings.db_schema},public"},
    )


def _set_status(
    session: Session,
    document_id: uuid.UUID,
    status: str,
    *,
    last_indexed_at: datetime | None = None,
) -> None:
    values: dict = {"indexing_status": status}
    if last_indexed_at is not None:
        values["last_indexed_at"] = last_indexed_at
    session.execute(
        update(KnowledgeDocument).where(KnowledgeDocument.id == document_id).values(**values)
    )


def _page_batches(pages: Iterator[tuple[int, str]], batch_size: int = PAGE_BATCH_SIZE) -> Iterator[list[tuple[int, str]]]:
    batch: list[tuple[int, str]] = []
    for page in pages:
        batch.append(page)
        if len(batch) >= batch_size:
            yield batch
            batch = []
    if batch:
        yield batch


def _save_chunk_batch(session: Session, document_id: uuid.UUID, records: list[dict]) -> None:
    for record in records:
        session.add(DocumentChunk(document_id=document_id, **record))
    session.commit()
    session.expunge_all()


def _advisory_lock_key(document_id: uuid.UUID) -> int:
    """Folds a UUID into the signed 64-bit int pg_advisory_lock expects."""
    return uuid.UUID(str(document_id)).int & 0x7FFFFFFFFFFFFFFF


def run_document_ingest(
    document_id: uuid.UUID,
    file_path: str | None,
    content_text: str | None,
) -> int:
    """Extract, chunk, embed, and persist a document in low-memory batches.

    Ingestion streams results to the DB in many small, separately-committed
    batches (see PAGE_BATCH_SIZE), so two concurrent ingests of the same
    document - e.g. a double click, or a retry firing while the first attempt
    is still running - would each compute chunk_index independently from 0
    and collide once both have written a while. A session-scoped Postgres
    advisory lock, held on a connection kept open for the whole call, rejects
    the second attempt outright instead of racing.
    """
    engine = _sync_engine()
    lock_key = _advisory_lock_key(document_id)
    lock_conn = engine.connect()
    acquired = False
    try:
        acquired = lock_conn.execute(text("SELECT pg_try_advisory_lock(:key)"), {"key": lock_key}).scalar()
        if not acquired:
            raise ValueError("This document is already being ingested. Wait for it to finish and try again.")

        try:
            with Session(engine) as session:
                _set_status(session, document_id, "processing")
                session.execute(delete(DocumentChunk).where(DocumentChunk.document_id == document_id))
                session.commit()

                document = session.get(KnowledgeDocument, document_id)
                title = document.title if document is not None else None

                total_chunks = 0
                chunk_index = 0

                if content_text is not None and content_text.strip():
                    records = build_chunk_records(content_text, title=title)
                    if not records:
                        raise ValueError("No content to index after chunking.")
                    _save_chunk_batch(session, document_id, records)
                    total_chunks = len(records)
                else:
                    if not file_path:
                        raise ValueError("No file path available for this document.")
                    for page_batch in _page_batches(iter_document_pages(file_path)):
                        records, chunk_index = build_chunk_records_from_pages_batch(
                            page_batch,
                            start_index=chunk_index,
                            embed_batch_size=EMBED_BATCH_SIZE,
                            title=title,
                        )
                        if records:
                            _save_chunk_batch(session, document_id, records)
                            total_chunks += len(records)
                        gc.collect()

                if total_chunks == 0:
                    raise ValueError(
                        "No extractable text found in the stored file - it may be a scanned/image-only document."
                    )

                _set_status(session, document_id, "indexed", last_indexed_at=datetime.now(timezone.utc))
                session.commit()
                logger.info("Ingest completed for %s: %d chunks indexed", document_id, total_chunks)
                return total_chunks
        except Exception:
            with Session(engine) as session:
                _set_status(session, document_id, "failed")
                session.commit()
            raise
    finally:
        if acquired:
            lock_conn.execute(text("SELECT pg_advisory_unlock(:key)"), {"key": lock_key})
        lock_conn.close()
