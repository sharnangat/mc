from functools import lru_cache

from sentence_transformers import SentenceTransformer

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
# Small cross-encoder. It does not replace the stored vectors; it re-scores
# the short candidate list for a single question, which is where most of the
# ranking errors in bi-encoder search come from.
RERANKER_MODEL = "cross-encoder/ms-marco-MiniLM-L-6-v2"
DEFAULT_BATCH_SIZE = 32


@lru_cache(maxsize=1)
def _get_model() -> SentenceTransformer:
    return SentenceTransformer(MODEL_NAME)


def embed_text(text: str) -> list[float]:
    return embed_texts([text])[0]


def embed_texts(texts: list[str], batch_size: int = DEFAULT_BATCH_SIZE) -> list[list[float]]:
    if not texts:
        return []
    model = _get_model()
    vectors = model.encode(
        texts,
        batch_size=batch_size,
        normalize_embeddings=True,
        show_progress_bar=False,
    )
    return [vector.tolist() for vector in vectors]


@lru_cache(maxsize=1)
def _get_reranker():
    from sentence_transformers import CrossEncoder

    return CrossEncoder(RERANKER_MODEL)


def rerank_passages(question: str, passages: list[str]) -> list[float]:
    """Higher score means the passage is more relevant to the question."""
    if not passages:
        return []
    scores = _get_reranker().predict(
        [(question, passage[:2000]) for passage in passages],
        batch_size=8,
        show_progress_bar=False,
    )
    return [float(score) for score in scores]
