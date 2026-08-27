"""Creates demo accounts and sample consultations so the app can be explored immediately.

Run with the venv's Python from the backend/ directory:
    .venv\\Scripts\\python.exe scripts\\seed_demo_data.py
"""

import asyncio
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db import SessionLocal
from app.models.catalog import ConsultationCategory, PricingPlan
from app.models.consultation import ExpertReview, FinalAnswer, Query
from app.models.identity import Role, User, UserRole
from app.models.knowledge import KnowledgeDocument
from app.services.rag import create_ai_answer
from app.services.security import hash_password

DEMO_PASSWORD = "Demo@1234"

DEMO_USERS = [
    ("customer@demo.com", "Demo Customer", "customer"),
    ("expert@demo.com", "Demo Expert", "expert"),
    ("admin@demo.com", "Demo Admin", "admin"),
]


async def get_or_create_user(db, email: str, full_name: str, role_code: str) -> User:
    user = await db.scalar(select(User).where(User.email == email))
    if user is None:
        user = User(email=email, full_name=full_name, password_hash=hash_password(DEMO_PASSWORD))
        db.add(user)
        await db.flush()

    role = await db.scalar(select(Role).where(Role.code == role_code))
    if role is None:
        raise RuntimeError(f"Role '{role_code}' not seeded - run db/seed.sql first")

    existing_link = await db.scalar(
        select(UserRole).where(UserRole.user_id == user.id, UserRole.role_id == role.id)
    )
    if existing_link is None:
        db.add(UserRole(user_id=user.id, role_id=role.id))

    return user


async def get_or_create_demo_query(db, customer: User, question: str, status: str) -> Query | None:
    existing = await db.scalar(select(Query).where(Query.question_text == question))
    if existing is not None:
        return existing

    category = await db.scalar(select(ConsultationCategory).where(ConsultationCategory.code == "heat_treatment"))
    plan = await db.scalar(select(PricingPlan).where(PricingPlan.code == "basic"))
    if category is None or plan is None:
        print("Skipping demo queries: consultation_categories/pricing_plans are not seeded (run db/seed.sql).")
        return None

    query = Query(
        customer_id=customer.id,
        consultation_category_id=category.id,
        pricing_plan_id=plan.id,
        question_text=question,
        status=status,
    )
    db.add(query)
    await db.flush()
    return query


async def main() -> None:
    async with SessionLocal() as db:
        users = {}
        for email, full_name, role_code in DEMO_USERS:
            users[role_code] = await get_or_create_user(db, email, full_name, role_code)
        await db.commit()
        print("Demo accounts ready:")
        for email, _, role_code in DEMO_USERS:
            print(f"  {email} / {DEMO_PASSWORD}  (role: {role_code})")

        customer = users["customer"]
        expert = users["expert"]

        has_enabled_doc = await db.scalar(
            select(KnowledgeDocument).where(KnowledgeDocument.is_enabled_for_ai.is_(True)).limit(1)
        )

        # 1. A query still awaiting payment.
        await get_or_create_demo_query(
            db,
            customer,
            "[DEMO] What material would you recommend for a forging die operating up to 550C?",
            status="pending_payment",
        )
        await db.commit()

        # 2. A paid query with an AI draft ready for expert review.
        draft_query = await get_or_create_demo_query(
            db,
            customer,
            "[DEMO] Why is the hardness of my 42CrMo4 component only 28 HRC after quenching and tempering at 600C?",
            status="paid",
        )
        if draft_query is not None and draft_query.status == "paid":
            if has_enabled_doc is None:
                print(
                    "No knowledge_documents are enabled for AI yet - the demo draft will report "
                    "'insufficient information', which is still a valid guardrail demo."
                )
            await create_ai_answer(db, draft_query)
            await db.commit()

        # 3. A fully completed consultation (approved + sent) to show the finished customer experience.
        sent_query = await get_or_create_demo_query(
            db,
            customer,
            "[DEMO] My EN19 component has 52 HRC after heat treatment but the required hardness is 38-42 HRC. What should I do?",
            status="paid",
        )
        if sent_query is not None and sent_query.status == "paid":
            ai_answer = await create_ai_answer(db, sent_query)
            await db.flush()

            review = ExpertReview(
                query_id=sent_query.id,
                ai_answer_id=ai_answer.id,
                expert_id=expert.id,
                action="approve",
                comment="Demo approval.",
            )
            db.add(review)
            await db.flush()

            db.add(
                FinalAnswer(
                    query_id=sent_query.id,
                    expert_review_id=review.id,
                    approved_by=expert.id,
                    final_technical_conclusion=ai_answer.technical_conclusion or "",
                    final_technical_reasoning=ai_answer.technical_reasoning,
                    final_recommended_action=ai_answer.recommended_action,
                    references_json=[],
                    sent_via=["website"],
                )
            )
            sent_query.status = "approved"
            await db.flush()

            final_answer = await db.scalar(select(FinalAnswer).where(FinalAnswer.query_id == sent_query.id))
            final_answer.sent_at = datetime.now(timezone.utc)
            sent_query.status = "sent"
            await db.commit()

        print("\nDemo queries seeded (idempotent - safe to re-run).")


if __name__ == "__main__":
    asyncio.run(main())
