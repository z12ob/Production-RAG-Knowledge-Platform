"""Create durable document processing jobs.

Revision ID: 20260829_0004
Revises: 20260829_0003
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0004"
down_revision: str | Sequence[str] | None = "20260829_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ingestion_jobs",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("document_id", sa.Uuid(), nullable=False),
        sa.Column(
            "status",
            sa.String(length=20),
            server_default=sa.text("'queued'"),
            nullable=False,
        ),
        sa.Column(
            "attempt_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
        sa.Column("failure_code", sa.String(length=50), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.Column("dispatched_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("attempt_count >= 0", name="attempt_count_nonnegative"),
        sa.CheckConstraint(
            "(status IN ('ready', 'failed')) = (completed_at IS NOT NULL)",
            name="completion_matches_status",
        ),
        sa.CheckConstraint(
            "failure_code IS NULL OR char_length(failure_code) BETWEEN 1 AND 50",
            name="failure_code_length",
        ),
        sa.CheckConstraint(
            "(status = 'failed') = (failure_code IS NOT NULL)",
            name="failure_code_matches_status",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'ready', 'failed')",
            name="status_valid",
        ),
        sa.ForeignKeyConstraint(
            ["document_id"],
            ["documents.id"],
            name="fk_ingestion_jobs_document_id_documents",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("document_id"),
    )
    op.execute(
        sa.text(
            """
            INSERT INTO ingestion_jobs (id, document_id, status, attempt_count)
            SELECT gen_random_uuid(), id, 'queued', 0
            FROM documents
            """
        )
    )


def downgrade() -> None:
    op.drop_table("ingestion_jobs")
