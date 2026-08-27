from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models.catalog import ConsultationCategory, PricingPlan
from app.schemas.catalog import ConsultationCategoryOut, PricingPlanOut

router = APIRouter(prefix="/catalog", tags=["catalog"])


@router.get("/consultation-categories", response_model=list[ConsultationCategoryOut])
async def list_consultation_categories(db: AsyncSession = Depends(get_db)):
    stmt = select(ConsultationCategory).where(ConsultationCategory.is_active.is_(True)).order_by(
        ConsultationCategory.sort_order
    )
    result = await db.scalars(stmt)
    return result.all()


@router.get("/pricing-plans", response_model=list[PricingPlanOut])
async def list_pricing_plans(db: AsyncSession = Depends(get_db)):
    stmt = select(PricingPlan).where(PricingPlan.is_active.is_(True))
    result = await db.scalars(stmt)
    return result.all()
