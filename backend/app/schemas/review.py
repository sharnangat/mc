import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

ReviewAction = Literal["approve", "edit", "reject", "request_more_info", "rerun_analysis", "comment"]


class ExpertReviewCreate(BaseModel):
    action: ReviewAction
    edited_technical_conclusion: str | None = None
    edited_technical_reasoning: str | None = None
    edited_recommended_action: str | None = None
    comment: str | None = None


class ExpertReviewOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query_id: uuid.UUID
    expert_id: uuid.UUID
    action: str
    comment: str | None
    created_at: datetime


class FinalAnswerOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query_id: uuid.UUID
    final_technical_conclusion: str
    final_technical_reasoning: str | None
    final_recommended_action: str | None
    references_json: list | dict | None
    sent_at: datetime | None
    sent_via: list[str]
