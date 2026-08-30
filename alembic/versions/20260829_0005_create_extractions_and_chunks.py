"""Create canonical document extractions and chunks.

Revision ID: 20260829_0005
Revises: 20260829_0004
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0005"
down_revision: str | Sequence[str] | None = "20260829_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_constraint("completion_matches_status", "ingestion_jobs", type_="check")
    op.drop_constraint("status_valid", "ingestion_jobs", type_="check")
    op.alter_column(
        "ingestion_jobs",
        "status",
        existing_type=sa.String(length=20),
        type_=sa.String(length=32),
        existing_nullable=False,
    )
    op.execute(
        sa.text(
            """
            UPDATE ingestion_jobs
            SET status = 'queued',
                attempt_count = 0,
                dispatched_at = NULL,
                started_at = NULL,
                completed_at = NULL,
                failure_code = NULL
            WHERE status IN ('processing', 'ready')
            """
        )
    )
    op.create_check_constraint(
        "status_valid",
        "ingestion_jobs",
        "status IN "
        "('queued', 'verifying', 'extracting', 'chunking', 'ready_for_indexing', 'failed')",
    )
    op.create_check_constraint(
        "completion_matches_status",
        "ingestion_jobs",
        "(status IN ('ready_for_indexing', 'failed')) = (completed_at IS NOT NULL)",
    )

    op.create_table(
        "document_extractions",
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("normalized_text", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("extractor_name", sa.String(length=50), nullable=False),
        sa.Column("extractor_version", sa.String(length=20), nullable=False),
        sa.Column("normalizer_version", sa.String(length=20), nullable=False),
        sa.Column("chunker_version", sa.String(length=20), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "character_count = char_length(normalized_text)",
            name="character_count_matches_text",
        ),
        sa.CheckConstraint("character_count > 0", name="character_count_positive"),
        sa.CheckConstraint(
            "char_length(chunker_version) BETWEEN 1 AND 20",
            name="chunker_version_length",
        ),
        sa.CheckConstraint(
            "char_length(extractor_name) BETWEEN 1 AND 50",
            name="extractor_name_length",
        ),
        sa.CheckConstraint(
            "char_length(extractor_version) BETWEEN 1 AND 20",
            name="extractor_version_length",
        ),
        sa.CheckConstraint(
            "char_length(normalizer_version) BETWEEN 1 AND 20",
            name="normalizer_version_length",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_extractions_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("document_id"),
    )
    op.create_table(
        "document_chunks",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("character_count", sa.Integer(), nullable=False),
        sa.Column("source_page_start", sa.Integer(), nullable=True),
        sa.Column("source_page_end", sa.Integer(), nullable=True),
        sa.Column("section_heading", sa.String(length=500), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "character_count = char_length(text)",
            name="character_count_matches_text",
        ),
        sa.CheckConstraint("character_count > 0", name="character_count_positive"),
        sa.CheckConstraint("ordinal >= 0", name="ordinal_nonnegative"),
        sa.CheckConstraint(
            "section_heading IS NULL OR char_length(section_heading) BETWEEN 1 AND 500",
            name="section_heading_length",
        ),
        sa.CheckConstraint(
            "(source_page_start IS NULL) = (source_page_end IS NULL)",
            name="source_pages_both_null_or_present",
        ),
        sa.CheckConstraint(
            "source_page_start IS NULL OR "
            "(source_page_start > 0 AND source_page_end >= source_page_start)",
            name="source_page_range_valid",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_document_chunks_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "document_id",
            "ordinal",
            name="uq_document_chunks_document_ordinal",
        ),
    )
    op.create_index(
        op.f("ix_document_chunks_document_id"),
        "document_chunks",
        ["document_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_document_chunks_document_id"), table_name="document_chunks")
    op.drop_table("document_chunks")
    op.drop_table("document_extractions")

    op.drop_constraint("completion_matches_status", "ingestion_jobs", type_="check")
    op.drop_constraint("status_valid", "ingestion_jobs", type_="check")
    op.execute(
        sa.text(
            """
            UPDATE ingestion_jobs
            SET status = CASE
                    WHEN status = 'ready_for_indexing' THEN 'ready'
                    WHEN status IN ('verifying', 'extracting', 'chunking') THEN 'processing'
                    ELSE status
                END
            """
        )
    )
    op.alter_column(
        "ingestion_jobs",
        "status",
        existing_type=sa.String(length=32),
        type_=sa.String(length=20),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "status_valid",
        "ingestion_jobs",
        "status IN ('queued', 'processing', 'ready', 'failed')",
    )
    op.create_check_constraint(
        "completion_matches_status",
        "ingestion_jobs",
        "(status IN ('ready', 'failed')) = (completed_at IS NOT NULL)",
    )
