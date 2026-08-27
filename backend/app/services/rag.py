import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consultation import AIAnswer, AIAnswerSource, Query
from app.models.knowledge import DocumentChunk, KnowledgeDocument
from app.services.embeddings import embed_text

logger = logging.getLogger(__name__)

TOP_K = 5
# Cosine distance cutoff (0 = identical, 2 = opposite) beyond which a chunk is
# not considered a real match. Tune this once a real embedding model is wired
# up in app/services/embeddings.py - the placeholder hashing embedding makes
# this threshold only loosely meaningful.
DISTANCE_THRESHOLD = 0.9

MODEL_NAME = "rag-template-stub"
MODEL_VERSION = "0.1.0"

INSUFFICIENT_INFO_MESSAGE = (
    "The available database does not contain sufficient information to answer this question. "
    "Please route this query for expert review or request additional customer documentation."
)


async def retrieve_chunks(db: AsyncSession, question_text: str, top_k: int = TOP_K):
    query_vector = embed_text(question_text)
    distance_col = DocumentChunk.embedding.cosine_distance(query_vector).label("distance")
    stmt = (
        select(DocumentChunk, KnowledgeDocument, distance_col)
        .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
        .where(KnowledgeDocument.is_enabled_for_ai.is_(True))
        .order_by(distance_col)
        .limit(top_k)
    )
    result = await db.execute(stmt)
    all_matches = result.all()
    matches = [
        (chunk, document, float(distance)) for chunk, document, distance in all_matches if distance <= DISTANCE_THRESHOLD
    ]
    logger.info(
        "Retrieval for %r: %d/%d candidates passed threshold %.2f (best distance=%s)",
        question_text[:80],
        len(matches),
        len(all_matches),
        DISTANCE_THRESHOLD,
        f"{all_matches[0][2]:.3f}" if all_matches else "n/a",
    )
    return matches


def draft_from_matches(matches: list[tuple[DocumentChunk, KnowledgeDocument, float]]) -> dict:
    """Composes a draft strictly from retrieved text - never invents content.

    This is a template-based placeholder for a real LLM call. Any future LLM
    integration here MUST be constrained to the same rule: answer only from
    the passed-in matches, and return insufficient_information=True rather
    than fabricating a conclusion, reference, or numeric value when matches
    are empty or weak (per the platform's AI guardrails).
    """
    if not matches:
        return {
            "technical_conclusion": INSUFFICIENT_INFO_MESSAGE,
            "technical_reasoning": None,
            "recommended_action": "Escalate to a metallurgical expert for manual review.",
            "insufficient_information": True,
        }

    reasoning_lines = [
        f"- From \"{doc.title}\"{f' (p.{chunk.page_number})' if chunk.page_number else ''}: {chunk.content_text[:400]}"
        for chunk, doc, _ in matches
    ]
    top_chunk, top_doc, _ = matches[0]
    return {
        "technical_conclusion": (
            f"Based on the approved knowledge base (primarily \"{top_doc.title}\"), the following applies: "
            f"{top_chunk.content_text[:500]}"
        ),
        "technical_reasoning": "\n".join(reasoning_lines),
        "recommended_action": (
            "Verify this conclusion against the cited sources and confirm applicability "
            "to the customer's exact material/process conditions before approving."
        ),
        "insufficient_information": False,
    }


async def create_ai_answer(db: AsyncSession, query: Query) -> AIAnswer:
    matches = await retrieve_chunks(db, query.question_text)
    draft = draft_from_matches(matches)
    if draft["insufficient_information"]:
        logger.info("Query %s: insufficient information in knowledge base", query.id)

    ai_answer = AIAnswer(
        query_id=query.id,
        model_name=MODEL_NAME,
        model_version=MODEL_VERSION,
        status="draft",
        **draft,
    )
    db.add(ai_answer)
    await db.flush()

    for chunk, document, distance in matches:
        db.add(
            AIAnswerSource(
                ai_answer_id=ai_answer.id,
                document_id=document.id,
                document_chunk_id=chunk.id,
                relevance_score=max(0.0, 1 - distance / 2),
                cited_text=chunk.content_text[:1000],
                page_number=chunk.page_number,
                section=chunk.section,
                clause_number=chunk.clause_number,
            )
        )

    query.status = "draft_ready"
    await db.flush()
    return ai_answer
