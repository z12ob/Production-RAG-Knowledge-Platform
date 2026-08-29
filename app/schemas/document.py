import uuid
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field

from app.models.ingestion_job import IngestionJobStatus


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime


class IngestionJobResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    document_id: uuid.UUID
    status: Annotated[
        IngestionJobStatus,
        Field(
            description=(
                "READY means file integrity checks passed and the source is ready for future "
                "extraction. It does not mean the document is searchable."
            )
        ),
    ]
    attempt_count: int
    failure_code: str | None
    created_at: datetime
    dispatched_at: datetime | None
    started_at: datetime | None
    completed_at: datetime | None
