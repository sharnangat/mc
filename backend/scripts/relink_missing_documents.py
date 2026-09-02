"""Relinks knowledge_documents rows whose stored file is missing on this
machine, then re-runs ingestion for them.

Background: source PDFs live in the repo's top-level pdf/ (tracked via Git
LFS). The admin upload API copies a file into backend/uploads/ (gitignored,
not part of the repo) at upload time and stores that copy's path on the row.
If the DB was restored/shared without that uploads/ folder coming along
(e.g. a fresh clone, or a synced database), rows end up pointing at files
that were never copied locally - the file is not "missing", it just never
existed on this machine. This script re-copies the matching source PDF from
pdf/ into uploads/documents/, updates the row's file_path, and re-ingests.

Run with the venv's Python from the backend/ directory:
    .venv\\Scripts\\python.exe scripts\\relink_missing_documents.py
"""

import asyncio
import shutil
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import select

from app.db import SessionLocal
from app.models.knowledge import KnowledgeDocument
from app.services.ingest_pipeline import run_document_ingest
from app.services.storage import BACKEND_ROOT, resolve_upload_path, upload_root

PDF_DIR = BACKEND_ROOT.parent / "pdf"

# title (as stored in knowledge_documents) -> source filename in pdf/
TITLE_TO_SOURCE = {
    "ASM Handbook Vol 9 - Metallography and Microstructures": "ASM Handbook - Vol 09 - Metallography and Microstructures (2733s).pdf",
    "ASM Handbook Vol 12 - Fractography": "ASM Handbook - Vol 12 - Fractography (1998s).pdf",
    "ASM Handbook Vol 19 - Fatigue and Fracture": "asm-metals-handbook-volume-19-fatigue-and-fracture1.pdf",
    "ASM Handbook - Failures of Metalworking Equipment": "Failures Metal working ASM HB.pdf",
    "Steel Heat Treatment: Metallurgy and Technologies": "Steel_Heat_Treatment_Metallurgy_And_Tech.pdf",
    "BS EN 10083-2:2006": "BS EN 10083-2-2006.pdf",
    "BS 970 Part 3 - Wrought Steels Specification": "BS-970-part3-Specification-for-Wrought-steels-for-mechanical-and-allied-engineering-purposes.pdf",
    "ASTM A494/A494M-12": "ASTM A94 A494M__12.pdf",
    "Nickel Alloy Product Handbook": "nickel-alloy-handbook.pdf",
}


async def main() -> None:
    async with SessionLocal() as db:
        documents = (await db.scalars(select(KnowledgeDocument))).all()

        to_ingest: list[uuid.UUID] = []
        for doc in documents:
            try:
                resolve_upload_path(doc.file_path)
                continue  # file already present, nothing to do
            except FileNotFoundError:
                pass

            source_name = TITLE_TO_SOURCE.get(doc.title)
            if source_name is None:
                print(f"SKIP  {doc.title!r}: file missing and no known source PDF mapped")
                continue

            source_path = PDF_DIR / source_name
            if not source_path.is_file():
                print(f"SKIP  {doc.title!r}: mapped source {source_path} does not exist")
                continue

            target_dir = upload_root() / "documents"
            target_dir.mkdir(parents=True, exist_ok=True)
            target_path = target_dir / f"{uuid.uuid4()}.pdf"
            print(f"COPY  {doc.title!r}: {source_path.name} -> {target_path.relative_to(BACKEND_ROOT)}")
            shutil.copyfile(source_path, target_path)

            doc.file_path = str(target_path.relative_to(BACKEND_ROOT))
            doc.indexing_status = "pending"
            to_ingest.append(doc.id)

        await db.commit()

    for doc_id in to_ingest:
        async with SessionLocal() as db:
            doc = await db.get(KnowledgeDocument, doc_id)
            print(f"INGEST {doc.title!r} ...")
        try:
            total = await asyncio.to_thread(run_document_ingest, doc_id, doc.file_path, None)
            print(f"  -> indexed, {total} chunks")
        except Exception as exc:  # noqa: BLE001 - report and continue with the rest
            print(f"  -> FAILED: {exc}")

    print("Done.")


if __name__ == "__main__":
    asyncio.run(main())
