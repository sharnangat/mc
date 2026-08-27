from app.services.embeddings import embed_text

CHUNK_WORD_SIZE = 200
CHUNK_WORD_OVERLAP = 40


def chunk_text(text: str, size: int = CHUNK_WORD_SIZE, overlap: int = CHUNK_WORD_OVERLAP) -> list[str]:
    """Splits plain text into overlapping word-count windows.

    This is the ingestion pipeline's chunking step for plain-text content.
    PDF/DOCX extraction and OCR (per the ingestion pipeline design) are not
    implemented yet - documents must be submitted as extracted plain text
    until an extractor is wired in here.
    """
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


def build_chunk_records(content_text: str) -> list[dict]:
    records = []
    for index, chunk in enumerate(chunk_text(content_text)):
        records.append(
            {
                "chunk_index": index,
                "content_text": chunk,
                "embedding": embed_text(chunk),
                "token_count": len(chunk.split()),
            }
        )
    return records


MIN_CHUNK_WORDS = 5


def build_chunk_records_from_pages(pages: list[tuple[int, str]]) -> list[dict]:
    """Chunks page-extracted text, keeping each chunk within a single page so citations stay accurate."""
    records = []
    index = 0
    for page_number, page_text in pages:
        for chunk in chunk_text(page_text):
            if len(chunk.split()) < MIN_CHUNK_WORDS:
                continue
            records.append(
                {
                    "chunk_index": index,
                    "page_number": page_number,
                    "content_text": chunk,
                    "embedding": embed_text(chunk),
                    "token_count": len(chunk.split()),
                }
            )
            index += 1
    return records
