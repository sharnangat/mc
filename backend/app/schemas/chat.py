import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel


class ChatRequest(BaseModel):
    message: str


class ChatSourceOut(BaseModel):
    document_id: uuid.UUID
    document_title: str
    page_number: int | None
    relevance_score: Decimal | None
    cited_text: str | None


class ChatResponse(BaseModel):
    technical_conclusion: str
    technical_reasoning: str | None
    recommended_action: str | None
    insufficient_information: bool
    sources: list[ChatSourceOut]


class ChatMessageOut(BaseModel):
    id: uuid.UUID
    question: str
    answer: ChatResponse
    created_at: datetime
