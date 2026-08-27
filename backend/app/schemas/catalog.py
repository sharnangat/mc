import uuid
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class ConsultationCategoryOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    sort_order: int


class PricingPlanOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    code: str
    name: str
    description: str | None
    price_inr: Decimal
    consultation_category_id: uuid.UUID | None


class PricingPlanUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    price_inr: Decimal | None = None
    is_active: bool | None = None
