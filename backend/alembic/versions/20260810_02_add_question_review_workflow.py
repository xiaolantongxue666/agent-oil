"""add question review workflow

Revision ID: 20260810_02
Revises: 20260810_01
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_02"
down_revision: str | None = "20260810_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "training_questions" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("training_questions")}
    if "status" not in columns:
        op.add_column(
            "training_questions",
            sa.Column("status", sa.String(length=24), nullable=False, server_default="published"),
        )
        op.create_index("ix_training_questions_status", "training_questions", ["status"])
    if "batch_code" not in columns:
        op.add_column(
            "training_questions",
            sa.Column("batch_code", sa.String(length=64), nullable=False, server_default="seed"),
        )
        op.create_index("ix_training_questions_batch_code", "training_questions", ["batch_code"])
    if "generated_by_ai" not in columns:
        op.add_column(
            "training_questions",
            sa.Column("generated_by_ai", sa.Boolean(), nullable=False, server_default=sa.false()),
        )
    if "generation_meta" not in columns:
        op.add_column(
            "training_questions",
            sa.Column("generation_meta", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
        )
    if "reviewed_by" not in columns:
        op.add_column("training_questions", sa.Column("reviewed_by", sa.Integer(), nullable=True))
        op.create_foreign_key(
            "fk_training_questions_reviewed_by_users",
            "training_questions",
            "users",
            ["reviewed_by"],
            ["id"],
            ondelete="SET NULL",
        )
    if "reviewed_at" not in columns:
        op.add_column(
            "training_questions", sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True)
        )

    inspector = sa.inspect(bind)
    if "training_sessions" in inspector.get_table_names():
        session_columns = {
            column["name"] for column in inspector.get_columns("training_sessions")
        }
        if "question_batch_code" not in session_columns:
            op.add_column(
                "training_sessions",
                sa.Column(
                    "question_batch_code",
                    sa.String(length=64),
                    nullable=False,
                    server_default="",
                ),
            )
            op.create_index(
                "ix_training_sessions_question_batch_code",
                "training_sessions",
                ["question_batch_code"],
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "training_questions" not in inspector.get_table_names():
        return
    if "training_sessions" in inspector.get_table_names():
        session_columns = {
            column["name"] for column in inspector.get_columns("training_sessions")
        }
        if "question_batch_code" in session_columns:
            op.drop_column("training_sessions", "question_batch_code")
    columns = {column["name"] for column in inspector.get_columns("training_questions")}
    for column in ("reviewed_at", "reviewed_by", "generation_meta", "generated_by_ai", "batch_code", "status"):
        if column in columns:
            op.drop_column("training_questions", column)
