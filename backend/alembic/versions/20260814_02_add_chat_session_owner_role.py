"""add chat session owner role

Revision ID: 20260814_02
Revises: 20260814_01
"""
from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260814_02"
down_revision: str | None = "20260814_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_sessions" not in tables:
        return
    columns = {col["name"] for col in sa.inspect(bind).get_columns("chat_sessions")}
    if "owner_role" not in columns:
        op.add_column(
            "chat_sessions",
            sa.Column("owner_role", sa.String(length=16), nullable=False, server_default="student"),
        )
        # 回填：按会话所有者的用户角色区分教师/学生对话
        if "users" in tables:
            op.execute(
                """
                UPDATE chat_sessions
                SET owner_role = (
                    SELECT users.role FROM users WHERE users.id = chat_sessions.user_id
                )
                WHERE EXISTS (
                    SELECT 1 FROM users WHERE users.id = chat_sessions.user_id
                )
                """
            )
    indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("chat_sessions")}
    if "ix_chat_sessions_owner_role" not in indexes:
        op.create_index("ix_chat_sessions_owner_role", "chat_sessions", ["owner_role"])


def downgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "chat_sessions" not in tables:
        return
    indexes = {idx["name"] for idx in sa.inspect(bind).get_indexes("chat_sessions")}
    if "ix_chat_sessions_owner_role" in indexes:
        op.drop_index("ix_chat_sessions_owner_role", table_name="chat_sessions")
    columns = {col["name"] for col in sa.inspect(bind).get_columns("chat_sessions")}
    if "owner_role" in columns:
        op.drop_column("chat_sessions", "owner_role")
