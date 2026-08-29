import uuid
from datetime import datetime
from typing import Annotated, Self

from pydantic import BaseModel, ConfigDict, StringConstraints, model_validator

KnowledgeBaseName = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=200),
]
KnowledgeBaseDescription = Annotated[str, StringConstraints(max_length=4000)]


class KnowledgeBaseCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: KnowledgeBaseName
    description: KnowledgeBaseDescription | None = None


class KnowledgeBaseUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: KnowledgeBaseName | None = None
    description: KnowledgeBaseDescription | None = None

    @model_validator(mode="after")
    def reject_null_name(self) -> Self:
        if "name" in self.model_fields_set and self.name is None:
            raise ValueError("name cannot be null")
        return self


class KnowledgeBaseResponse(BaseModel):
    model_config = ConfigDict(extra="forbid", from_attributes=True)

    id: uuid.UUID
    owner_id: uuid.UUID
    name: str
    description: str | None
    created_at: datetime
    updated_at: datetime
