import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings

BACKEND_ROOT = Path(__file__).resolve().parents[2]


def upload_root() -> Path:
    return Path(settings.upload_dir).resolve()


def resolve_upload_path(file_path: str) -> Path:
    """Resolve a stored upload path (relative to backend root) to an on-disk file."""
    path = Path(file_path)
    resolved = path if path.is_absolute() else BACKEND_ROOT / path
    if not resolved.is_file():
        raise FileNotFoundError(f"Stored file not found: {file_path}")
    return resolved


async def save_upload(file: UploadFile, subdir: str) -> tuple[str, str]:
    """Saves an uploaded file to disk and returns (stored_path, original_filename)."""
    target_dir = upload_root() / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix
    stored_name = f"{uuid.uuid4()}{suffix}"
    stored_path = target_dir / stored_name

    # Stream in chunks so a large handbook is not held entirely in memory.
    with stored_path.open("wb") as out:
        while chunk := await file.read(1024 * 1024):
            out.write(chunk)

    # Stored relative to backend root so deploy paths stay portable.
    try:
        stored_relative = stored_path.relative_to(BACKEND_ROOT)
    except ValueError:
        stored_relative = stored_path
    return str(stored_relative), file.filename or stored_name
