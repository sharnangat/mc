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


def _chunk_items_from_pages(pages: list[tuple[int, str]]) -> list[tuple[int | None, str]]:
    chunk_items: list[tuple[int | None, str]] = []
    for page_number, page_text in pages:
        for chunk in chunk_text(page_text):
            if len(chunk.split()) >= MIN_CHUNK_WORDS:
                chunk_items.append((page_number, chunk))
    return chunk_items


def _records_from_chunk_items(
    chunk_items: list[tuple[int | None, str]],
    start_index: int,
    embed_batch_size: int,
) -> list[dict]:
    records: list[dict] = []
    for offset in range(0, len(chunk_items), embed_batch_size):
        batch = chunk_items[offset : offset + embed_batch_size]
        texts = [text for _, text in batch]
        embeddings = embed_texts(texts, batch_size=embed_batch_size)
        for item_index, ((page_number, text), embedding) in enumerate(zip(batch, embeddings)):
            records.append(
                {
                    "chunk_index": start_index + offset + item_index,
                    "page_number": page_number,
                    "content_text": text,
                    "embedding": embedding,
                    "token_count": len(text.split()),
                }
            )
    return records


def build_chunk_records(content_text: str) -> list[dict]:
    chunk_items = [(None, chunk) for chunk in chunk_text(content_text)]
    return _records_from_chunk_items(chunk_items, start_index=0, embed_batch_size=32)


def build_chunk_records_from_pages(pages: list[tuple[int, str]]) -> list[dict]:
    """Chunks page-extracted text, keeping each chunk within a single page so citations stay accurate."""
    chunk_items = _chunk_items_from_pages(pages)
    return _records_from_chunk_items(chunk_items, start_index=0, embed_batch_size=32)


def build_chunk_records_from_pages_batch(
    pages: list[tuple[int, str]],
    start_index: int,
    embed_batch_size: int = 32,
) -> tuple[list[dict], int]:
    """Build chunk records for a page batch; returns (records, next_chunk_index)."""
    chunk_items = _chunk_items_from_pages(pages)
    records = _records_from_chunk_items(chunk_items, start_index, embed_batch_size)
    return records, start_index + len(records)
