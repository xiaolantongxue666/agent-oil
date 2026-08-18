"""add teacher reviewed flag to knowledge chunks

Revision ID: 20260809_02
Revises: 20260809_01
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_02"
down_revision: str | None = "20260809_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_chunks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
    if "reviewed" not in columns:
        op.add_column(
            "knowledge_chunks",
            sa.Column("reviewed", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
        op.create_index("ix_knowledge_chunks_reviewed", "knowledge_chunks", ["reviewed"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "knowledge_chunks" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("knowledge_chunks")}
    if "reviewed" in columns:
        op.drop_column("knowledge_chunks", "reviewed")
