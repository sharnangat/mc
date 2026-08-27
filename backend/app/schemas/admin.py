import uuid
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict

DocumentType = Literal[
    "standard",
    "handbook",
    "internal_report",
    "customer_document",
    "lab_procedure",
    "heat_treatment_procedure",
    "welding_procedure",
    "material_specification",
    "research_paper",
    "other",
]


class KnowledgeDocumentCreate(BaseModel):
    title: str
    document_type: DocumentType
    standard_name: str | None = None
    edition_year: int | None = None
    revision: str | None = None
    source_owner: str | None = None
    licence_status: Literal["owned", "licensed", "public_domain", "internal", "unlicensed"] = "unlicensed"
    access_permission: Literal["public", "internal", "restricted", "admin_only"] = "restricted"
    notes: str | None = None


class KnowledgeDocumentUpdate(BaseModel):
    title: str | None = None
    is_enabled_for_ai: bool | None = None
    licence_status: str | None = None
    access_permission: str | None = None
    notes: str | None = None


class KnowledgeDocumentOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    title: str
    document_type: str
    standard_name: str | None
    edition_year: int | None
    revision: str | None
    source_owner: str | None
    licence_status: str
    access_permission: str
    is_enabled_for_ai: bool
    indexing_status: str
    uploaded_at: datetime
    last_indexed_at: datetime | None
