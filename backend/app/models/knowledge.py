import uuid
from datetime import datetime

from pgvector.sqlalchemy import Vector
from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.config import settings
from app.db import Base
from app.models.common import SCHEMA, UUIDPk


class KnowledgeCategory(UUIDPk, Base):
    __tablename__ = "knowledge_categories"
    __table_args__ = {"schema": SCHEMA}

    parent_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.knowledge_categories.id", ondelete="CASCADE")
    )
    name: Mapped[str] = mapped_column(String, nullable=False)
    sort_order: Mapped[int] = mapped_column(server_default=text("0"))


class KnowledgeDocument(UUIDPk, Base):
    __tablename__ = "knowledge_documents"
    __table_args__ = {"schema": SCHEMA}

    title: Mapped[str] = mapped_column(String, nullable=False)
    document_type: Mapped[str] = mapped_column(String, nullable=False)
    standard_name: Mapped[str | None] = mapped_column(String)
    edition_year: Mapped[int | None] = mapped_column(Integer)
    revision: Mapped[str | None] = mapped_column(String)
    source_owner: Mapped[str | None] = mapped_column(String)
    licence_status: Mapped[str] = mapped_column(String, server_default=text("'unlicensed'"))
    access_permission: Mapped[str] = mapped_column(String, server_default=text("'restricted'"))
    is_enabled_for_ai: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    indexing_status: Mapped[str] = mapped_column(String, server_default=text("'pending'"))
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    file_hash: Mapped[str | None] = mapped_column(String)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    last_indexed_at: Mapped[datetime | None] = mapped_column()
    notes: Mapped[str | None] = mapped_column(Text)


class DocumentChunk(UUIDPk, Base):
    __tablename__ = "document_chunks"
    __table_args__ = (
        UniqueConstraint("document_id", "chunk_index"),
        {"schema": SCHEMA},
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.knowledge_documents.id", ondelete="CASCADE"), nullable=False
    )
    chunk_index: Mapped[int] = mapped_column(Integer, nullable=False)
    page_number: Mapped[int | None] = mapped_column(Integer)
    section: Mapped[str | None] = mapped_column(String)
    clause_number: Mapped[str | None] = mapped_column(String)
    content_text: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[list[float] | None] = mapped_column(Vector(settings.embedding_dim))
    token_count: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
