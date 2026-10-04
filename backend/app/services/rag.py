import asyncio
import logging
import math
import re
import uuid

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consultation import AIAnswer, AIAnswerSource, Query
from app.models.knowledge import DocumentChunk, KnowledgeDocument
from app.services.embeddings import embed_text, rerank_passages

logger = logging.getLogger(__name__)

TOP_K = 5
# How many hits each leg returns before they are merged and re-scored.
CANDIDATE_K = 20
# Cross-encoder only looks at the best fused candidates. It is the slow step.
RERANK_POOL = 16
# Reciprocal-rank fusion constant. 60 is the usual value from the RRF paper.
RRF_K = 60
# ms-marco MiniLM logits. Below this the passage is treated as not an answer,
# which is more precise than the old cosine-distance cutoff of 0.9.
RERANK_MIN_LOGIT = -1.0
# Overlapping windows from the same page otherwise fill the result list.
MAX_CHUNKS_PER_PAGE = 2

_STOPWORDS = frozenset(
    {
        "a", "an", "and", "are", "as", "at", "be", "by", "can", "do", "does",
        "for", "from", "how", "in", "is", "it", "of", "on", "or", "please",
        "that", "the", "this", "to", "what", "when", "where", "which", "with",
    }
)
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+")

MODEL_NAME = "rag-template-stub"
MODEL_VERSION = "0.2.0"

INSUFFICIENT_INFO_MESSAGE = (
    "The available database does not contain sufficient information to answer this question. "
    "Please route this query for expert review or request additional customer documentation."
)


class _Hit:
    __slots__ = ("chunk", "document", "distance", "rerank")

    def __init__(self, chunk: DocumentChunk, document: KnowledgeDocument, distance: float | None):
        self.chunk = chunk
        self.document = document
        self.distance = distance
        self.rerank: float | None = None


def _keyword_tsquery(question: str) -> str | None:
    """OR of the content words. AND-ing a full question drops passages that omit 'what' or 'the'."""
    tokens: list[str] = []
    seen: set[str] = set()
    for raw in _TOKEN_RE.findall(question.lower()):
        if raw in _STOPWORDS or raw in seen:
            continue
        if len(raw) < 3 and not any(char.isdigit() for char in raw):
            continue
        seen.add(raw)
        tokens.append(raw)
        if len(tokens) == 8:
            break
    if not tokens:
        return None
    return " | ".join(tokens)


def _logit_to_distance(logit: float) -> float:
    """Map a reranker logit onto cosine distance so existing relevance = 1 - distance/2 equals the probability."""
    probability = 1 / (1 + math.exp(-logit))
    return (1 - probability) * 2


def _fuse(vector_rows, keyword_rows) -> list[_Hit]:
    scores: dict[uuid.UUID, float] = {}
    hits: dict[uuid.UUID, _Hit] = {}
    for rank, (chunk, document, distance) in enumerate(vector_rows, start=1):
        hits[chunk.id] = _Hit(chunk, document, float(distance))
        scores[chunk.id] = 1 / (RRF_K + rank)
    for rank, (chunk, document, _rank) in enumerate(keyword_rows, start=1):
        if chunk.id not in hits:
            hits[chunk.id] = _Hit(chunk, document, None)
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (RRF_K + rank)
    return sorted(hits.values(), key=lambda hit: scores[hit.chunk.id], reverse=True)


def _diversify(hits: list[_Hit], top_k: int) -> list[_Hit]:
    chosen: list[_Hit] = []
    per_page: dict[tuple[uuid.UUID, int | None], int] = {}
    for hit in hits:
        key = (hit.document.id, hit.chunk.page_number)
        if per_page.get(key, 0) >= MAX_CHUNKS_PER_PAGE:
            continue
        per_page[key] = per_page.get(key, 0) + 1
        chosen.append(hit)
        if len(chosen) == top_k:
            break
    return chosen


async def _vector_candidates(db: AsyncSession, question_text: str):
    distance_col = DocumentChunk.embedding.cosine_distance(embed_text(question_text)).label("distance")
    stmt = (
        select(DocumentChunk, KnowledgeDocument, distance_col)
        .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
        .where(
            KnowledgeDocument.is_enabled_for_ai.is_(True),
            DocumentChunk.embedding.is_not(None),
        )
        .order_by(distance_col)
        .limit(CANDIDATE_K)
    )
    result = await db.execute(stmt)
    return result.all()


async def _keyword_candidates(db: AsyncSession, question_text: str):
    tsquery_text = _keyword_tsquery(question_text)
    if tsquery_text is None:
        return []
    chunk_vec = func.to_tsvector("english", DocumentChunk.content_text)
    title_vec = func.to_tsvector("english", func.coalesce(KnowledgeDocument.title, ""))
    tsquery = func.to_tsquery("english", tsquery_text)
    rank = (func.ts_rank_cd(chunk_vec, tsquery) + func.ts_rank_cd(title_vec, tsquery)).label("rank")
    stmt = (
        select(DocumentChunk, KnowledgeDocument, rank)
        .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
        .where(
            KnowledgeDocument.is_enabled_for_ai.is_(True),
            or_(chunk_vec.op("@@")(tsquery), title_vec.op("@@")(tsquery)),
        )
        .order_by(rank.desc())
        .limit(CANDIDATE_K)
    )
    try:
        async with db.begin_nested():
            result = await db.execute(stmt)
            return result.all()
    except Exception:
        logger.exception("Keyword retrieval failed for %r", question_text[:80])
        return []


async def retrieve_chunks(db: AsyncSession, question_text: str, top_k: int = TOP_K):
    """Hybrid search: nearest embeddings plus exact-term matches, then a cross-encoder re-score.

    Vector search alone misses alloy numbers and standard names. Keyword search
    alone misses paraphrases. Reciprocal rank fusion keeps a hit that either
    leg found, and the cross-encoder decides which of those passages actually
    answer the question.
    """
    vector_rows = await _vector_candidates(db, question_text)
    keyword_rows = await _keyword_candidates(db, question_text)
    fused = _fuse(vector_rows, keyword_rows)
    if not fused:
        logger.info("Retrieval for %r: no candidates", question_text[:80])
        return []

    pool = fused[:RERANK_POOL]
    passages = [f"{hit.document.title}\n{hit.chunk.content_text}" for hit in pool]
    try:
        scores = await asyncio.to_thread(rerank_passages, question_text, passages)
    except Exception:
        logger.exception("Reranker failed; keeping hybrid order")
        scores = None

    if scores is not None:
        for hit, score in zip(pool, scores):
            hit.rerank = score
            hit.distance = _logit_to_distance(score)
        pool.sort(key=lambda hit: hit.rerank if hit.rerank is not None else -999.0, reverse=True)
        kept = [hit for hit in pool if hit.rerank is not None and hit.rerank >= RERANK_MIN_LOGIT]
    else:
        kept = pool

    selected = _diversify(kept, top_k)
    logger.info(
        "Retrieval for %r: vector=%d keyword=%d fused=%d kept=%d (best rerank=%s)",
        question_text[:80],
        len(vector_rows),
        len(keyword_rows),
        len(fused),
        len(selected),
        f"{selected[0].rerank:.2f}" if selected and selected[0].rerank is not None else "n/a",
    )
    return [
        (hit.chunk, hit.document, hit.distance if hit.distance is not None else 1.0)
        for hit in selected
    ]


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

    reasoning_lines = []
    for idx, (chunk, document, _) in enumerate(matches, start=1):
        page = f", p. {chunk.page_number}" if chunk.page_number else ""
        reasoning_lines.append(f"{idx}. {document.title}{page}: {chunk.content_text[:400]}")
    top_chunk, top_document, _ = matches[0]
    return {
        "technical_conclusion": (
            f"Based on {top_document.title}, the following applies: "
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
