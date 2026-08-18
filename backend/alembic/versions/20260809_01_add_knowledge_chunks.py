"""add reviewable structured knowledge chunks

Revision ID: 20260809_01
Revises:
Create Date: 2026-08-09
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260809_01"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    # 首次部署由随后执行的 seed/create_all 建完整表；历史库在此增量升级。
    if "knowledge_items" not in tables or "knowledge_points" not in tables:
        return

    item_columns = {column["name"] for column in inspector.get_columns("knowledge_items")}
    if "file_hash" not in item_columns:
        op.add_column("knowledge_items", sa.Column("file_hash", sa.String(64), nullable=True))
        op.create_index("ix_knowledge_items_file_hash", "knowledge_items", ["file_hash"])

    if "knowledge_chunks" in tables:
        return
    op.create_table(
        "knowledge_chunks",
        sa.Column("knowledge_item_id", sa.Integer(), nullable=False),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("heading", sa.String(255), nullable=False, server_default=""),
        sa.Column("chapter", sa.String(255), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("page_start", sa.Integer(), nullable=True),
        sa.Column("page_end", sa.Integer(), nullable=True),
        sa.Column("char_start", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("char_end", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("checksum", sa.String(64), nullable=False),
        sa.Column("knowledge_point_id", sa.Integer(), nullable=True),
        sa.Column("knowledge_point_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("knowledge_point_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("ability", sa.String(64), nullable=False, server_default=""),
        sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("match_reason", sa.String(255), nullable=False, server_default=""),
        sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vector_embedded", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("qdrant_point_id", sa.String(128), nullable=True),
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_item_id"], ["knowledge_items.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_point_id"], ["knowledge_points.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_item_id", "chunk_index", name="uq_knowledge_chunk_index"
        ),
    )
    op.create_index(
        "ix_knowledge_chunks_knowledge_item_id", "knowledge_chunks", ["knowledge_item_id"]
    )
    op.create_index(
        "ix_knowledge_chunks_knowledge_point_id", "knowledge_chunks", ["knowledge_point_id"]
    )
    op.create_index("ix_knowledge_chunks_checksum", "knowledge_chunks", ["checksum"])
    op.create_index("ix_knowledge_chunks_ability", "knowledge_chunks", ["ability"])
    op.create_index("ix_knowledge_chunks_enabled", "knowledge_chunks", ["enabled"])


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "knowledge_chunks" in tables:
        op.drop_table("knowledge_chunks")
    if "knowledge_items" in tables:
        columns = {column["name"] for column in inspector.get_columns("knowledge_items")}
        if "file_hash" in columns:
            op.drop_column("knowledge_items", "file_hash")
