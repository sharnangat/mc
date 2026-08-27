import uuid
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class CreateOrderResponse(BaseModel):
    payment_id: uuid.UUID
    gateway: str
    gateway_order_id: str
    amount_inr: Decimal
    currency: str


class ConfirmPaymentRequest(BaseModel):
    gateway_order_id: str
    gateway_payment_id: str
    gateway_signature: str | None = None


class PaymentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    query_id: uuid.UUID
    amount_inr: Decimal
    currency: str
    gateway: str
    status: str
    paid_at: datetime | None
    created_at: datetime
