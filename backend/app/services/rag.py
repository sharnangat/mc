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
MODEL_VERSION = "0.3.0"

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


def _content_tokens(question: str) -> list[str]:
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
    return tokens


def _keyword_tsquery(question: str) -> str | None:
    """Require grade/standard numbers, then any of the topic words.

    A plain OR matches every page that says "steel" or "temperature". A question
    about 4140 tempering must mention 4140 and at least one of those topics.
    """
    tokens = _content_tokens(question)
    if not tokens:
        return None
    anchors = [token for token in tokens if any(char.isdigit() for char in token)]
    others = [token for token in tokens if token not in anchors]
    if anchors and others:
        return f"({' | '.join(anchors)}) & ({' | '.join(others)})"
    if 2 <= len(tokens) <= 4:
        return " & ".join(tokens)
    return " | ".join(tokens)


def focus_excerpt(text: str, question: str, limit: int = 700) -> str:
    """Keep the sentences that contain the question's terms, in reading order.

    The start of a 200-word chunk is often the previous topic. The cited answer
    should be the sentences that actually mention the grade or property asked for.
    """
    tokens = _content_tokens(question)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
    if not tokens or not sentences:
        return text[:limit]

    def mentions(sentence: str) -> int:
        lowered = sentence.lower()
        return sum(2 if any(char.isdigit() for char in token) else 1 for token in tokens if token in lowered)

    chosen = [sentence for sentence in sentences if mentions(sentence) > 0]
    if not chosen:
        chosen = sentences[:2]
    return " ".join(chosen)[:limit]


def _logit_to_distance(logit: float) -> float:
    """Map a reranker logit onto cosine distance so existing relevance = 1 - distance/2 equals the probability."""
    probability = 1 / (1 + math.exp(-logit))
    return (1 - probability) * 2


def _absorb(hits: dict[uuid.UUID, _Hit], scores: dict[uuid.UUID, float], rows, *, distance: bool) -> None:
    for rank, (chunk, document, third) in enumerate(rows, start=1):
        if chunk.id not in hits:
            hits[chunk.id] = _Hit(chunk, document, float(third) if distance else None)
        elif distance and (hits[chunk.id].distance is None or float(third) < hits[chunk.id].distance):
            hits[chunk.id].distance = float(third)
        scores[chunk.id] = scores.get(chunk.id, 0.0) + 1 / (RRF_K + rank)


def _fuse(*ranked_lists: tuple[list, bool]) -> list[_Hit]:
    scores: dict[uuid.UUID, float] = {}
    hits: dict[uuid.UUID, _Hit] = {}
    for rows, use_distance in ranked_lists:
        _absorb(hits, scores, rows, distance=use_distance)
    return sorted(hits.values(), key=lambda hit: scores[hit.chunk.id], reverse=True)


def _anchor_bonus(text: str, anchors: list[str]) -> float:
    """Prefer a passage that actually contains the grade or standard number."""
    if not anchors:
        return 0.0
    lowered = text.lower()
    covered = sum(anchor in lowered for anchor in anchors) / len(anchors)
    return 3.0 * covered


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
    tokens = _content_tokens(question_text)
    anchors = [token for token in tokens if any(char.isdigit() for char in token)]
    condensed = " ".join(tokens)
    vector_rows = await _vector_candidates(db, question_text)
    # Handbook prose looks like "4140 tempering", not "what is the tempering temperature of".
    condensed_rows = []
    if condensed and condensed != question_text.strip().lower():
        condensed_rows = await _vector_candidates(db, condensed)
    keyword_rows = await _keyword_candidates(db, question_text)
    fused = _fuse((vector_rows, True), (condensed_rows, True), (keyword_rows, False))
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
            bonus = _anchor_bonus(f"{hit.document.title}\n{hit.chunk.content_text}", anchors)
            hit.rerank = score + bonus
            hit.distance = _logit_to_distance(hit.rerank)
        pool.sort(key=lambda hit: hit.rerank if hit.rerank is not None else -999.0, reverse=True)
        kept = [hit for hit in pool if hit.rerank is not None and hit.rerank >= RERANK_MIN_LOGIT]
    else:
        for hit in pool:
            hit.rerank = _anchor_bonus(f"{hit.document.title}\n{hit.chunk.content_text}", anchors)
        pool.sort(key=lambda hit: hit.rerank if hit.rerank is not None else 0.0, reverse=True)
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


def draft_from_matches(
    matches: list[tuple[DocumentChunk, KnowledgeDocument, float]],
    question_text: str = "",
    include_citations: bool = True,
) -> dict:
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

    top_chunk, top_document, _ = matches[0]
    excerpt = focus_excerpt(top_chunk.content_text, question_text, limit=700)
    if not include_citations:
        return {
            "technical_conclusion": excerpt,
            "technical_reasoning": None,
            "recommended_action": None,
            "insufficient_information": False,
        }

    reasoning_lines = []
    for idx, (chunk, document, _) in enumerate(matches, start=1):
        page = f", p. {chunk.page_number}" if chunk.page_number else ""
        reasoning_lines.append(
            f"{idx}. {document.title}{page}: {focus_excerpt(chunk.content_text, question_text, limit=400)}"
        )
    return {
        "technical_conclusion": (
            f"Based on {top_document.title}, the following applies: {excerpt}"
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
    draft = draft_from_matches(matches, query.question_text)
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
                cited_text=focus_excerpt(chunk.content_text, query.question_text, limit=1000),
                page_number=chunk.page_number,
                section=chunk.section,
                clause_number=chunk.clause_number,
            )
        )

    query.status = "draft_ready"
    await db.flush()
    return ai_answer
