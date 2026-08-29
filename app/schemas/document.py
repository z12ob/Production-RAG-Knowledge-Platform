import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict


class DocumentResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    knowledge_base_id: uuid.UUID
    original_filename: str
    content_type: str
    size_bytes: int
    checksum_sha256: str
    created_at: datetime
