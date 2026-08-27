import logging
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.catalog import PricingPlan
from app.models.consultation import Payment, Query
from app.models.identity import User
from app.schemas.payment import ConfirmPaymentRequest, CreateOrderResponse, PaymentOut
from app.services.deps import get_current_user
from app.services.payment_gateway import gateway
from app.services.rag import create_ai_answer

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/payments", tags=["payments"])


@router.post("/{query_id}/create-order", response_model=CreateOrderResponse)
async def create_order(query_id: uuid.UUID, user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Query not found")
    if query.customer_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not authorized")
    if query.status != "pending_payment":
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"Query is already in status '{query.status}'")

    plan = await db.get(PricingPlan, query.pricing_plan_id)
    order_id = gateway.create_order(plan.price_inr, "INR")

    payment = Payment(
        query_id=query.id,
        customer_id=user.id,
        pricing_plan_id=plan.id,
        amount_inr=plan.price_inr,
        currency="INR",
        gateway=gateway.name,
        gateway_order_id=order_id,
        status="created",
    )
    db.add(payment)
    await db.commit()
    await db.refresh(payment)
    logger.info("Payment order created for query %s: %s %s via %s", query.id, plan.price_inr, "INR", gateway.name)

    return CreateOrderResponse(
        payment_id=payment.id,
        gateway=gateway.name,
        gateway_order_id=order_id,
        amount_inr=plan.price_inr,
        currency="INR",
    )


@router.post("/{query_id}/confirm", response_model=PaymentOut)
async def confirm_payment(
    query_id: uuid.UUID,
    payload: ConfirmPaymentRequest,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    query = await db.get(Query, query_id)
    if query is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Query not found")
    if query.customer_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Not authorized")

    payment = await db.scalar(
        select(Payment).where(
            Payment.query_id == query_id, Payment.gateway_order_id == payload.gateway_order_id
        )
    )
    if payment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Order not found for this query")
    if payment.status == "paid":
        return payment

    if not gateway.verify_payment(payload.gateway_order_id, payload.gateway_payment_id, payload.gateway_signature):
        payment.status = "failed"
        await db.commit()
        logger.warning("Payment verification failed for query %s (order %s)", query_id, payload.gateway_order_id)
        raise HTTPException(status.HTTP_402_PAYMENT_REQUIRED, detail="Payment verification failed")

    payment.status = "paid"
    payment.gateway_payment_id = payload.gateway_payment_id
    payment.paid_at = datetime.now(timezone.utc)
    query.status = "paid"
    await db.flush()
    logger.info("Payment confirmed for query %s: %s %s", query.id, payment.amount_inr, payment.currency)

    query.status = "ai_processing"
    await db.flush()
    await create_ai_answer(db, query)

    await db.commit()
    await db.refresh(payment)
    return payment
