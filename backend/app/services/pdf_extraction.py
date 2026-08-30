from __future__ import annotations

from collections.abc import Iterator
from pathlib import Path

import pypdf
from pypdf.errors import PdfReadError, PdfStreamError

from app.services.storage import resolve_upload_path


def _clean_text(text: str) -> str:
    """Strips NUL bytes and other control characters some PDFs embed in watermarks/footers.

    Postgres' UTF8 text columns reject NUL bytes outright (CharacterNotInRepertoireError),
    so this must run before any extracted text reaches the database.
    """
    return "".join(ch for ch in text if ch == "\n" or ch == "\t" or ord(ch) >= 32).strip()


def iter_pdf_pages(file_path: str | Path) -> Iterator[tuple[int, str]]:
    """Yield (page_number, text) pairs one page at a time to limit memory use."""
    resolved = resolve_upload_path(str(file_path))
    try:
        reader = pypdf.PdfReader(resolved, strict=False)
    except (PdfReadError, PdfStreamError) as exc:
        raise ValueError(
            "Could not read this PDF - the file may be corrupt, truncated, or password-protected."
        ) from exc
    for index, page in enumerate(reader.pages):
        text = _clean_text(page.extract_text() or "")
        if text:
            yield (index + 1, text)


def extract_pdf_pages(file_path: str | Path) -> list[tuple[int, str]]:
    """Returns (page_number, text) pairs, 1-indexed, skipping pages with no extractable text."""
    return list(iter_pdf_pages(file_path))


def iter_document_pages(file_path: str) -> Iterator[tuple[int, str]]:
    """Yield (page_number, text) pairs for a stored document."""
    resolved = resolve_upload_path(file_path)
    suffix = resolved.suffix.lower()
    if suffix == ".pdf":
        yield from iter_pdf_pages(resolved)
        return
    if suffix in (".txt", ".md"):
        text = _clean_text(resolved.read_text(encoding="utf-8", errors="replace"))
        if text:
            yield (1, text)
        return
    raise ValueError(f"No text extractor available for file type '{suffix}'")


def extract_document_pages(file_path: str) -> list[tuple[int, str]]:
    """Extracts all (page_number, text) pairs for a stored document."""
    return list(iter_document_pages(file_path))
