import asyncio
import logging
import math
import re
import uuid

from sqlalchemy import case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.consultation import AIAnswer, AIAnswerSource, Query
from app.models.knowledge import DocumentChunk, KnowledgeDocument
from app.services.embeddings import embed_text, rerank_passages

logger = logging.getLogger(__name__)

TOP_K = 5
# How many hits each leg returns before they are merged and re-scored.
CANDIDATE_K = 30
# Cross-encoder only looks at the best fused candidates. It is the slow step.
RERANK_POOL = 16
# Reciprocal-rank fusion constant. 60 is the usual value from the RRF paper.
RRF_K = 60
# ms-marco MiniLM logits. Below this the passage is treated as not an answer,
# which is more precise than the old cosine-distance cutoff of 0.9.
RERANK_MIN_LOGIT = -1.0
# A page that literally contains the grade can rank a bit lower than prose
# that merely discusses the same property. It still has to clear this floor.
EXACT_MIN_LOGIT = -2.0
# Overlapping windows from the same page otherwise fill the result list.
MAX_CHUNKS_PER_PAGE = 2
# Long chunks dilute the cross-encoder. Score each half and keep the better one.
WINDOW_WORDS = 120
WINDOW_OVERLAP = 35

_STOPWORDS = frozenset(
    {
        "a", "an", "about", "after", "also", "and", "any", "are", "as",
        "at", "be", "been", "between", "but", "by", "can", "compare", "did",
        "difference", "do", "does", "each", "explain", "following", "for",
        "from", "give", "how", "in", "into", "is", "it", "more", "most", "not",
        "of", "on", "or", "other", "please", "should", "tell", "than", "that",
        "the", "their", "there", "these", "this", "through", "to", "under",
        "use", "used", "using", "versus", "was", "were", "what", "when",
        "where", "which", "will", "with", "would", "your",
    }
)
# Keeps alloy designations whole: 17-4PH, Ti-6Al-4V, 4140.
_TOKEN_RE = re.compile(r"[A-Za-z0-9]+(?:-[A-Za-z0-9]+)*")
# Retrieval only. The text shown to the user stays the book wording.
_SEARCH_EXPANSIONS = {
    "hrc": "rockwell hardness",
    "hrb": "rockwell hardness",
    "hv": "vickers hardness",
    "hb": "brinell hardness",
    "uts": "tensile strength",
    "ys": "yield strength",
    "pwht": "postweld heat treatment",
    "haz": "heat affected zone",
    "cct": "continuous cooling transformation",
    "ttt": "time temperature transformation",
    "qt": "quench temper",
}

MODEL_NAME = "rag-template-stub"
MODEL_VERSION = "0.4.0"

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
        if len(tokens) == 12:
            break
    return tokens


def _query_terms(question: str) -> tuple[list[str], list[str], list[str]]:
    """Split a question into grade numbers, topic words, and hyphenated names.

    Hyphenated names stay intact for exact matching. Their alphabetic pieces
    ("post", "weld") still participate in full-text search.
    """
    tokens = _content_tokens(question)
    exact = [token for token in tokens if "-" in token]
    atoms = [token for token in tokens if "-" not in token]
    for token in tokens:
        for word in _SEARCH_EXPANSIONS.get(token, "").split():
            if word in _STOPWORDS or word in atoms or "-" in word or len(word) < 3:
                continue
            atoms.append(word)
        if "-" not in token:
            continue
        for part in token.split("-"):
            if part in _STOPWORDS or part in atoms or any(char.isdigit() for char in part) or len(part) < 4:
                continue
            atoms.append(part)
    anchors = [token for token in atoms if any(char.isdigit() for char in token)]
    topics = [token for token in atoms if token not in anchors]
    return anchors, topics, exact


def _strict_tsquery(question: str) -> str | None:
    """Require every grade number and the most specific topic words.

    OR-ing "steel" with "temperature" matches most of a handbook. AND-ing the
    grade with the property drops those pages.
    """
    anchors, topics, _ = _query_terms(question)
    if anchors and topics:
        return f"({' & '.join(anchors)}) & ({' | '.join(topics)})"
    if anchors:
        return " & ".join(anchors)
    if not topics:
        return None
    specific = sorted(topics, key=len, reverse=True)[:4]
    return specific[0] if len(specific) == 1 else " & ".join(specific)


def _loose_tsquery(question: str) -> str | None:
    """Wider query used only when the strict one finds too few pages."""
    anchors, topics, _ = _query_terms(question)
    if anchors and topics:
        return f"({' | '.join(anchors)}) & ({' | '.join(topics)})"
    terms = anchors + topics
    if not terms:
        return None
    return " | ".join(terms)


def _websearch_text(question: str) -> str:
    """websearch_to_tsquery treats a hyphen as NOT, which breaks 17-4PH."""
    return re.sub(r"(?<=\w)-(?=\w)", " ", question)


def _contains_term(haystack_lower: str, term: str) -> bool:
    if any(char.isdigit() for char in term) or "-" in term:
        pattern = rf"(?:^|[^a-z0-9]){re.escape(term)}(?:[^a-z0-9]|$)"
    else:
        pattern = rf"(?:^|[^a-z]){re.escape(term)}"
    return re.search(pattern, haystack_lower) is not None


def _match_terms(question: str) -> list[str]:
    anchors, topics, exact = _query_terms(question)
    terms: list[str] = []
    for term in exact + anchors + topics:
        if term not in terms:
            terms.append(term)
    return terms


def _designations(question: str) -> list[str]:
    anchors, _, exact = _query_terms(question)
    terms: list[str] = []
    for term in exact + anchors:
        if term not in terms:
            terms.append(term)
    return terms


def _trim(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    clipped = text[:limit].rsplit(" ", 1)[0]
    return clipped or text[:limit]


def focus_excerpt(text: str, question: str, limit: int = 700) -> str:
    """Quote the sentence that best matches the question, plus the one after it.

    A 200-word chunk often starts on the previous topic, and a grade number can
    appear in almost every sentence. Weight terms that show up in fewer sentences
    so the quoted span is the one that actually answers the question. The words
    themselves are copied from the book.
    """
    terms = _match_terms(question)
    sentences = [part.strip() for part in re.split(r"(?<=[.!?])\s+|\n+", text) if part.strip()]
    if not sentences:
        return ""
    if not terms or len(sentences) == 1:
        return _trim(sentences[0], limit)

    weights: list[tuple[str, float]] = []
    for term in terms:
        hits = sum(1 for sentence in sentences if _contains_term(sentence.lower(), term))
        if hits == 0:
            continue
        base = 3 if any(char.isdigit() for char in term) or "-" in term else 1
        weights.append((term, base * (len(sentences) / hits)))
    if not weights:
        return _trim(" ".join(sentences[:2]), limit)

    def score_at(index: int) -> float:
        lowered = sentences[index].lower()
        return sum(weight for term, weight in weights if _contains_term(lowered, term))

    scores = [score_at(index) for index in range(len(sentences))]
    if max(scores) <= 0:
        return _trim(" ".join(sentences[:2]), limit)

    best = max(
        range(len(scores)),
        key=lambda index: (scores[index], scores[index + 1] if index + 1 < len(scores) else 0),
    )
    chosen = [sentences[best]]
    if best + 1 < len(sentences) and scores[best + 1] > 0:
        chosen.append(sentences[best + 1])
    return _trim(" ".join(chosen), limit)


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


def _coverage(text: str, designations: list[str]) -> float:
    if not designations:
        return 0.0
    lowered = text.lower()
    return sum(_contains_term(lowered, term) for term in designations) / len(designations)


def _passage_windows(text: str) -> list[str]:
    words = text.split()
    if len(words) <= WINDOW_WORDS:
        return [text]
    half = len(words) // 2
    return [
        " ".join(words[: half + WINDOW_OVERLAP]),
        " ".join(words[max(0, half - WINDOW_OVERLAP) :]),
    ]


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


def _merge_rows(primary, extra):
    merged = list(primary)
    seen = {chunk.id for chunk, _, _ in merged}
    for row in extra:
        if row[0].id in seen:
            continue
        seen.add(row[0].id)
        merged.append(row)
    return merged


async def _fts_candidates(db: AsyncSession, tsquery, question_text: str):
    chunk_vec = func.to_tsvector("english", DocumentChunk.content_text)
    title_vec = func.to_tsvector("english", func.coalesce(KnowledgeDocument.title, ""))
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


async def _keyword_candidates(db: AsyncSession, question_text: str):
    """Strict full-text first, then a wider query if that misses the page."""
    strict = _strict_tsquery(question_text)
    rows = []
    if strict:
        rows = await _fts_candidates(db, func.to_tsquery("english", strict), question_text)
    loose = _loose_tsquery(question_text)
    if loose and loose != strict and len(rows) < 8:
        rows = _merge_rows(rows, await _fts_candidates(db, func.to_tsquery("english", loose), question_text))
    return rows


async def _web_candidates(db: AsyncSession, question_text: str):
    """Natural-language AND query. Postgres drops stopwords itself."""
    return await _fts_candidates(
        db,
        func.websearch_to_tsquery("english", _websearch_text(question_text)),
        question_text,
    )


async def _exact_candidates(db: AsyncSession, question_text: str):
    """Whole-token match for names that full-text search splits, such as 17-4PH."""
    anchors, _, exact = _query_terms(question_text)
    terms: list[str] = []
    for term in exact + [anchor for anchor in anchors if any(char.isalpha() for char in anchor)]:
        if term not in terms:
            terms.append(term)
    if not terms:
        return []

    content = func.lower(DocumentChunk.content_text)
    title = func.lower(func.coalesce(KnowledgeDocument.title, ""))
    conditions = []
    score = None
    for term in terms:
        pattern = rf"(?:^|[^a-z0-9]){re.escape(term)}(?:[^a-z0-9]|$)"
        cond = or_(content.op("~")(pattern), title.op("~")(pattern))
        conditions.append(cond)
        piece = case((cond, 1), else_=0)
        score = piece if score is None else score + piece
    stmt = (
        select(DocumentChunk, KnowledgeDocument, score.label("rank"))
        .join(KnowledgeDocument, DocumentChunk.document_id == KnowledgeDocument.id)
        .where(KnowledgeDocument.is_enabled_for_ai.is_(True), or_(*conditions))
        .order_by(score.desc())
        .limit(CANDIDATE_K)
    )
    try:
        async with db.begin_nested():
            result = await db.execute(stmt)
            return result.all()
    except Exception:
        logger.exception("Exact retrieval failed for %r", question_text[:80])
        return []


def _rerank_question(question_text: str) -> str:
    """Add expansions such as HRC -> hardness for scoring only, not for the reply."""
    original = {token for token in _content_tokens(question_text)}
    _, topics, _ = _query_terms(question_text)
    extras = [topic for topic in topics if topic not in original]
    if not extras:
        return question_text
    return f"{question_text} {' '.join(extras)}"


def _vector_query(question_text: str) -> str | None:
    """Handbook-like query: grade and property words, plus a few expansions."""
    anchors, topics, exact = _query_terms(question_text)
    terms = exact + anchors + topics
    if not terms:
        return None
    condensed = " ".join(terms)
    if condensed == question_text.strip().lower():
        return None
    return condensed


def _rank_key(hit: _Hit, designations: list[str]) -> float:
    """Reranker score, with a small nudge when more of the asked grades are present."""
    base = hit.rerank if hit.rerank is not None else -999.0
    if not designations:
        return base
    body = f"{hit.document.title}\n{hit.chunk.content_text}"
    return base + 0.35 * _coverage(body, designations)


async def retrieve_chunks(db: AsyncSession, question_text: str, top_k: int = TOP_K):
    """Hybrid search: embeddings, full-text, and exact grade names, then a cross-encoder.

    Vector search misses alloy numbers. A loose keyword search matches every page
    that says "steel". Fusion keeps both, the cross-encoder scores the best span
    inside each chunk, and a question that names a grade prefers pages that
    contain that grade. The reranker still decides which of those pages answers it.
    """
    designations = _designations(question_text)
    condensed = _vector_query(question_text)
    vector_rows = await _vector_candidates(db, question_text)
    condensed_rows = []
    if condensed:
        condensed_rows = await _vector_candidates(db, condensed)
    web_rows = await _web_candidates(db, question_text)
    keyword_rows = await _keyword_candidates(db, question_text)
    exact_rows = await _exact_candidates(db, question_text)
    # One lexical vote. Counting web and keyword separately let word overlap
    # crowd the paraphrases that only vector search found out of the rerank pool.
    lexical_rows = _merge_rows(web_rows, keyword_rows)
    fused = _fuse(
        (vector_rows, True),
        (condensed_rows, True),
        (lexical_rows, False),
        (exact_rows, False),
    )
    if not fused:
        logger.info("Retrieval for %r: no candidates", question_text[:80])
        return []

    pool = list(fused[:RERANK_POOL])
    # A hyphenated grade can lose the fusion sort when ordinary words match more
    # pages. Keep those exact pages in the rerank set anyway.
    present = {hit.chunk.id for hit in pool}
    fused_by_id = {hit.chunk.id: hit for hit in fused}
    added = 0
    for chunk, document, _third in exact_rows:
        if chunk.id in present:
            continue
        pool.append(fused_by_id.get(chunk.id) or _Hit(chunk, document, None))
        present.add(chunk.id)
        added += 1
        if added == 8:
            break
    windows: list[str] = []
    owners: list[_Hit] = []
    for hit in pool:
        for window in _passage_windows(hit.chunk.content_text):
            windows.append(f"{hit.document.title}\n{window}")
            owners.append(hit)
    try:
        scores = await asyncio.to_thread(rerank_passages, _rerank_question(question_text), windows)
    except Exception:
        logger.exception("Reranker failed; keeping hybrid order")
        scores = None

    if scores is not None:
        best: dict[uuid.UUID, float] = {}
        for hit, score in zip(owners, scores):
            previous = best.get(hit.chunk.id)
            if previous is None or score > previous:
                best[hit.chunk.id] = score
        for hit in pool:
            hit.rerank = best.get(hit.chunk.id, -999.0)
            hit.distance = _logit_to_distance(hit.rerank)
        named = [
            hit
            for hit in pool
            if hit.rerank >= EXACT_MIN_LOGIT
            and _coverage(f"{hit.document.title}\n{hit.chunk.content_text}", designations) > 0
        ]
        semantic = [hit for hit in pool if hit.rerank >= RERANK_MIN_LOGIT]
        kept = named if designations and named else semantic
        kept.sort(key=lambda hit: _rank_key(hit, designations), reverse=True)
    else:
        kept = pool

    selected = _diversify(kept, top_k)
    logger.info(
        "Retrieval for %r: vector=%d web=%d keyword=%d exact=%d fused=%d kept=%d (best rerank=%s)",
        question_text[:80],
        len(vector_rows),
        len(web_rows),
        len(keyword_rows),
        len(exact_rows),
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
