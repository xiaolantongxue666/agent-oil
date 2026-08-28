"""add assistant metadata to chat messages

Revision ID: 20260824_01
Revises: 20260816_01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260824_01"
down_revision: str | None = "20260816_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _assistant_meta_column() -> sa.Column:
    return sa.Column(
        "assistant_meta",
        sa.JSON().with_variant(postgresql.JSONB(), "postgresql"),
        nullable=False,
        server_default="{}",
    )


def upgrade() -> None:
    if context.is_offline_mode():
        op.add_column("chat_messages", _assistant_meta_column())
        return
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_messages" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("chat_messages")}
    if "assistant_meta" not in columns:
        op.add_column("chat_messages", _assistant_meta_column())


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_column("chat_messages", "assistant_meta")
        return
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_messages" not in tables:
        return
    columns = {column["name"] for column in sa.inspect(bind).get_columns("chat_messages")}
    if "assistant_meta" in columns:
        op.drop_column("chat_messages", "assistant_meta")
