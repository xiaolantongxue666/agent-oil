"""add system settings

Revision ID: 20260814_03
Revises: 20260814_02
"""
from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260814_03"
down_revision: str | None = "20260814_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "system_settings" in tables:
        return
    op.create_table(
        "system_settings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("key", sa.String(64), nullable=False),
        sa.Column("value", sa.Text(), nullable=False, server_default=""),
        sa.Column("category", sa.String(32), nullable=False, server_default="llm"),
        sa.Column("description", sa.String(256), nullable=False, server_default=""),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("updated_by", sa.Integer(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_system_settings_key", "system_settings", ["key"], unique=True)
    op.create_index("ix_system_settings_category", "system_settings", ["category"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "system_settings" not in tables:
        return
    op.drop_index("ix_system_settings_category", table_name="system_settings")
    op.drop_index("ix_system_settings_key", table_name="system_settings")
    op.drop_table("system_settings")
