from app.services.embeddings import embed_texts

CHUNK_WORD_SIZE = 200
CHUNK_WORD_OVERLAP = 40


def chunk_text(text: str, size: int = CHUNK_WORD_SIZE, overlap: int = CHUNK_WORD_OVERLAP) -> list[str]:
    """Splits plain text into overlapping word-count windows."""
    words = text.split()
    if not words:
        return []

    chunks = []
    start = 0
    while start < len(words):
        end = start + size
        chunks.append(" ".join(words[start:end]))
        if end >= len(words):
            break
        start = end - overlap
    return chunks


MIN_CHUNK_WORDS = 5


def _build_records(chunk_items: list[tuple[int | None, str]]) -> list[dict]:
    """Build chunk records with batched embeddings."""
    texts = [text for _, text in chunk_items]
    embeddings = embed_texts(texts)
    records = []
    for index, ((page_number, text), embedding) in enumerate(zip(chunk_items, embeddings)):
        records.append(
            {
                "chunk_index": index,
                "page_number": page_number,
                "content_text": text,
                "embedding": embedding,
                "token_count": len(text.split()),
            }
        )
    return records


def build_chunk_records(content_text: str) -> list[dict]:
    chunks = [(None, chunk) for chunk in chunk_text(content_text)]
    return _build_records(chunks)


def build_chunk_records_from_pages(pages: list[tuple[int, str]]) -> list[dict]:
    """Chunks page-extracted text, keeping each chunk within a single page so citations stay accurate."""
    chunk_items: list[tuple[int | None, str]] = []
    for page_number, page_text in pages:
        for chunk in chunk_text(page_text):
            if len(chunk.split()) < MIN_CHUNK_WORDS:
                continue
            chunk_items.append((page_number, chunk))
    return _build_records(chunk_items)
