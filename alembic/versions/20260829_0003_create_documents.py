"""Create document metadata storage.

Revision ID: 20260829_0003
Revises: 20260829_0002
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0003"
down_revision: str | Sequence[str] | None = "20260829_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "documents",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("knowledge_base_id", sa.Uuid(), nullable=False),
        sa.Column("original_filename", sa.String(length=255), nullable=False),
        sa.Column("content_type", sa.String(length=100), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("checksum_sha256", sa.String(length=64), nullable=False),
        sa.Column("storage_key", sa.String(length=100), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "checksum_sha256 ~ '^[0-9a-f]{64}$'",
            name="checksum_sha256_format",
        ),
        sa.CheckConstraint(
            "char_length(content_type) BETWEEN 1 AND 100",
            name="content_type_length",
        ),
        sa.CheckConstraint(
            "char_length(original_filename) BETWEEN 1 AND 255",
            name="original_filename_length",
        ),
        sa.CheckConstraint("size_bytes > 0", name="size_bytes_positive"),
        sa.CheckConstraint(
            "char_length(storage_key) BETWEEN 1 AND 100",
            name="storage_key_length",
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_base_id"],
            ["knowledge_bases.id"],
            name="fk_documents_knowledge_base_id_knowledge_bases",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("storage_key"),
    )
    op.create_index(
        "ix_documents_knowledge_base_id",
        "documents",
        ["knowledge_base_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_documents_knowledge_base_id", table_name="documents")
    op.drop_table("documents")
