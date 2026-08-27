import uuid
from pathlib import Path

from fastapi import UploadFile

from app.config import settings


async def save_upload(file: UploadFile, subdir: str) -> tuple[str, str]:
    """Saves an uploaded file to disk and returns (stored_path, original_filename)."""
    target_dir = Path(settings.upload_dir) / subdir
    target_dir.mkdir(parents=True, exist_ok=True)

    suffix = Path(file.filename or "").suffix
    stored_name = f"{uuid.uuid4()}{suffix}"
    stored_path = target_dir / stored_name

    contents = await file.read()
    stored_path.write_bytes(contents)

    return str(stored_path), file.filename or stored_name
