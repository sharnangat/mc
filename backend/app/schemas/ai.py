import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class AIAnswerSourceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    document_title: str | None = None
    relevance_score: Decimal | None
    cited_text: str | None
    page_number: int | None
    section: str | None
    clause_number: str | None


class AIAnswerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query_id: uuid.UUID
    model_name: str
    model_version: str
    technical_conclusion: str | None
    technical_reasoning: str | None
    recommended_action: str | None
    insufficient_information: bool
    status: str
    created_at: datetime
    sources: list[AIAnswerSourceOut] = []
