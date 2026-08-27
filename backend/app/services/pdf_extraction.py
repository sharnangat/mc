from pathlib import Path

import pypdf


def _clean_text(text: str) -> str:
    """Strips NUL bytes and other control characters some PDFs embed in watermarks/footers.

    Postgres' UTF8 text columns reject NUL bytes outright (CharacterNotInRepertoireError),
    so this must run before any extracted text reaches the database.
    """
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32).strip()


def extract_pdf_pages(file_path: str) -> list[tuple[int, str]]:
    """Returns (page_number, text) pairs, 1-indexed, skipping pages with no extractable text."""
    reader = pypdf.PdfReader(file_path)
    pages = []
    for index, page in enumerate(reader.pages):
        text = _clean_text(page.extract_text() or "")
        if text:
            pages.append((index + 1, text))
    return pages


def extract_document_pages(file_path: str) -> list[tuple[int, str]]:
    """Extracts (page_number, text) pairs for a stored document, dispatching on file extension."""
    suffix = Path(file_path).suffix.lower()
    if suffix == ".pdf":
        return extract_pdf_pages(file_path)
    if suffix in (".txt", ".md"):
        text = _clean_text(Path(file_path).read_text(encoding="utf-8", errors="replace"))
        return [(1, text)] if text else []
    raise ValueError(f"No text extractor available for file type '{suffix}'")
