import uuid
from datetime import datetime
from decimal import Decimal

from sqlalchemy import ARRAY, Boolean, ForeignKey, Numeric, String, Text, text
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.common import SCHEMA, UUIDPk


class Query(UUIDPk, Base):
    __tablename__ = "queries"
    __table_args__ = {"schema": SCHEMA}

    query_code: Mapped[str | None] = mapped_column(String, unique=True)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id"), nullable=False)
    consultation_category_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.consultation_categories.id"), nullable=False
    )
    pricing_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.pricing_plans.id"), nullable=False
    )
    question_text: Mapped[str] = mapped_column(Text, nullable=False)
    priority: Mapped[str] = mapped_column(String, server_default=text("'normal'"))
    status: Mapped[str] = mapped_column(String, server_default=text("'pending_payment'"))
    assigned_expert_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
    updated_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class QueryAttachment(UUIDPk, Base):
    __tablename__ = "query_attachments"
    __table_args__ = {"schema": SCHEMA}

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.queries.id", ondelete="CASCADE"), nullable=False
    )
    attachment_type: Mapped[str] = mapped_column(String, nullable=False)
    file_name: Mapped[str] = mapped_column(String, nullable=False)
    file_path: Mapped[str] = mapped_column(String, nullable=False)
    uploaded_by: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id"))
    uploaded_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class Payment(UUIDPk, Base):
    __tablename__ = "payments"
    __table_args__ = {"schema": SCHEMA}

    query_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.queries.id"), nullable=False)
    customer_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id"), nullable=False)
    pricing_plan_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.pricing_plans.id"), nullable=False
    )
    amount_inr: Mapped[Decimal] = mapped_column(Numeric(10, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String, server_default=text("'INR'"))
    gateway: Mapped[str] = mapped_column(String, server_default=text("'razorpay'"))
    gateway_order_id: Mapped[str | None] = mapped_column(String)
    gateway_payment_id: Mapped[str | None] = mapped_column(String)
    status: Mapped[str] = mapped_column(String, server_default=text("'created'"))
    raw_response: Mapped[dict | None] = mapped_column(JSONB)
    paid_at: Mapped[datetime | None] = mapped_column()
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class AIAnswer(UUIDPk, Base):
    __tablename__ = "ai_answers"
    __table_args__ = {"schema": SCHEMA}

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.queries.id", ondelete="CASCADE"), nullable=False
    )
    prompt_template_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.prompt_templates.id")
    )
    model_name: Mapped[str] = mapped_column(String, nullable=False)
    model_version: Mapped[str] = mapped_column(String, nullable=False)
    technical_conclusion: Mapped[str | None] = mapped_column(Text)
    technical_reasoning: Mapped[str | None] = mapped_column(Text)
    recommended_action: Mapped[str | None] = mapped_column(Text)
    insufficient_information: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    status: Mapped[str] = mapped_column(String, server_default=text("'draft'"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class AIAnswerSource(UUIDPk, Base):
    __tablename__ = "ai_answer_sources"
    __table_args__ = {"schema": SCHEMA}

    ai_answer_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.ai_answers.id", ondelete="CASCADE"), nullable=False
    )
    document_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.knowledge_documents.id"), nullable=False
    )
    document_chunk_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.document_chunks.id", ondelete="SET NULL")
    )
    relevance_score: Mapped[float | None] = mapped_column(Numeric(5, 4))
    cited_text: Mapped[str | None] = mapped_column(Text)
    page_number: Mapped[int | None] = mapped_column()
    section: Mapped[str | None] = mapped_column(String)
    clause_number: Mapped[str | None] = mapped_column(String)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class ExpertReview(UUIDPk, Base):
    __tablename__ = "expert_reviews"
    __table_args__ = {"schema": SCHEMA}

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.queries.id", ondelete="CASCADE"), nullable=False
    )
    ai_answer_id: Mapped[uuid.UUID | None] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.ai_answers.id"))
    expert_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id"), nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    edited_technical_conclusion: Mapped[str | None] = mapped_column(Text)
    edited_technical_reasoning: Mapped[str | None] = mapped_column(Text)
    edited_recommended_action: Mapped[str | None] = mapped_column(Text)
    comment: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))


class FinalAnswer(UUIDPk, Base):
    __tablename__ = "final_answers"
    __table_args__ = {"schema": SCHEMA}

    query_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.queries.id"), unique=True, nullable=False
    )
    expert_review_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.expert_reviews.id"), nullable=False
    )
    approved_by: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), ForeignKey(f"{SCHEMA}.users.id"), nullable=False)
    final_technical_conclusion: Mapped[str] = mapped_column(Text, nullable=False)
    final_technical_reasoning: Mapped[str | None] = mapped_column(Text)
    final_recommended_action: Mapped[str | None] = mapped_column(Text)
    references_json: Mapped[dict | list | None] = mapped_column(JSONB)
    sent_at: Mapped[datetime | None] = mapped_column()
    sent_via: Mapped[list[str]] = mapped_column(ARRAY(String), server_default=text("'{}'"))
    created_at: Mapped[datetime] = mapped_column(server_default=text("now()"))
