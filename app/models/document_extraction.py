import uuid
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, DateTime, ForeignKey, Integer, String, Text, Uuid, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.document import Document


class DocumentExtraction(Base):
    __tablename__ = "document_extractions"
    __table_args__ = (
        CheckConstraint("character_count > 0", name="character_count_positive"),
        CheckConstraint(
            "character_count = char_length(normalized_text)",
            name="character_count_matches_text",
        ),
        CheckConstraint(
            "char_length(extractor_name) BETWEEN 1 AND 50",
            name="extractor_name_length",
        ),
        CheckConstraint(
            "char_length(extractor_version) BETWEEN 1 AND 20",
            name="extractor_version_length",
        ),
        CheckConstraint(
            "char_length(normalizer_version) BETWEEN 1 AND 20",
            name="normalizer_version_length",
        ),
        CheckConstraint(
            "char_length(chunker_version) BETWEEN 1 AND 20",
            name="chunker_version_length",
        ),
    )

    document_id: Mapped[uuid.UUID] = mapped_column(
        Uuid,
        ForeignKey("documents.id", ondelete="CASCADE"),
        primary_key=True,
    )
    normalized_text: Mapped[str] = mapped_column(Text, nullable=False)
    character_count: Mapped[int] = mapped_column(Integer, nullable=False)
    extractor_name: Mapped[str] = mapped_column(String(50), nullable=False)
    extractor_version: Mapped[str] = mapped_column(String(20), nullable=False)
    normalizer_version: Mapped[str] = mapped_column(String(20), nullable=False)
    chunker_version: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
    document: Mapped["Document"] = relationship(back_populates="extraction")
