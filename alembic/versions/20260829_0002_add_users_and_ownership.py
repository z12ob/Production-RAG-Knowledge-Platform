"""Add users and knowledge base ownership.

Revision ID: 20260829_0002
Revises: 20260829_0001
Create Date: 2026-08-29
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260829_0002"
down_revision: str | Sequence[str] | None = "20260829_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    anonymous_count = connection.scalar(sa.text("SELECT count(*) FROM knowledge_bases"))
    if anonymous_count:
        raise RuntimeError(
            "Cannot require knowledge base ownership while anonymous rows exist. "
            "Resolve the pre-production data explicitly, then retry the migration."
        )

    op.create_table(
        "users",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("password_hash", sa.String(length=255), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("CURRENT_TIMESTAMP"),
            nullable=False,
        ),
        sa.CheckConstraint("email = lower(email)", name="email_normalized"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("email"),
    )
    op.add_column(
        "knowledge_bases",
        sa.Column("owner_id", sa.Uuid(), nullable=False),
    )
    op.create_foreign_key(
        "fk_knowledge_bases_owner_id_users",
        "knowledge_bases",
        "users",
        ["owner_id"],
        ["id"],
        ondelete="RESTRICT",
    )
    op.create_index(
        "ix_knowledge_bases_owner_id",
        "knowledge_bases",
        ["owner_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_knowledge_bases_owner_id", table_name="knowledge_bases")
    op.drop_constraint(
        "fk_knowledge_bases_owner_id_users",
        "knowledge_bases",
        type_="foreignkey",
    )
    op.drop_column("knowledge_bases", "owner_id")
    op.drop_table("users")
