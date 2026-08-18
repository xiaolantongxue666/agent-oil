"""add knowledge chunk structure fields

Revision ID: 20260816_01
Revises: 20260814_03
"""
from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260816_01"
down_revision: str | None = "20260814_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "knowledge_chunks" in tables:
        chunk_columns = {c["name"] for c in inspector.get_columns("knowledge_chunks")}
        if "heading_path" not in chunk_columns:
            op.add_column(
                "knowledge_chunks",
                sa.Column("heading_path", sa.String(512), nullable=False, server_default=""),
            )
        if "chunk_type" not in chunk_columns:
            op.add_column(
                "knowledge_chunks",
                sa.Column("chunk_type", sa.String(16), nullable=False, server_default="text"),
            )
    if "knowledge_items" in tables:
        item_columns = {c["name"] for c in inspector.get_columns("knowledge_items")}
        if "file_path" not in item_columns:
            op.add_column(
                "knowledge_items",
                sa.Column("file_path", sa.String(500), nullable=False, server_default=""),
            )


def downgrade() -> None:
    inspector = sa.inspect(op.get_bind())
    tables = set(inspector.get_table_names())
    if "knowledge_items" in tables:
        item_columns = {c["name"] for c in inspector.get_columns("knowledge_items")}
        if "file_path" in item_columns:
            op.drop_column("knowledge_items", "file_path")
    if "knowledge_chunks" in tables:
        chunk_columns = {c["name"] for c in inspector.get_columns("knowledge_chunks")}
        if "chunk_type" in chunk_columns:
            op.drop_column("knowledge_chunks", "chunk_type")
        if "heading_path" in chunk_columns:
            op.drop_column("knowledge_chunks", "heading_path")
