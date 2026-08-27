import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

from app.schemas.review import FinalAnswerOut

AttachmentType = Literal[
    "chemical_composition",
    "hardness_result",
    "tensile_result",
    "heat_treatment_cycle",
    "microstructure_photo",
    "spectro_report",
    "test_report",
    "failure_photo",
    "drawing_specification",
    "welding_detail",
    "pwht_detail",
    "other",
]


class QueryCreate(BaseModel):
    consultation_category_id: uuid.UUID
    pricing_plan_id: uuid.UUID
    question_text: str
    priority: Literal["normal", "high", "urgent"] = "normal"


class AttachmentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    attachment_type: str
    file_name: str
    uploaded_at: datetime


class QueryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query_code: str | None
    customer_id: uuid.UUID
    consultation_category_id: uuid.UUID
    pricing_plan_id: uuid.UUID
    question_text: str
    priority: str
    status: str
    assigned_expert_id: uuid.UUID | None
    created_at: datetime
    updated_at: datetime


class QueryDetailOut(QueryOut):
    attachments: list[AttachmentOut] = []
    final_answer: FinalAnswerOut | None = None
