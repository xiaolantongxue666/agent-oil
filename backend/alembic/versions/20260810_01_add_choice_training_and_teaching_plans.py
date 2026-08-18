"""add choice training and teaching plans

Revision ID: 20260810_01
Revises: 20260809_02
Create Date: 2026-08-10
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260810_01"
down_revision: str | None = "20260809_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    existing = set(sa.inspect(bind).get_table_names())
    # 空库由启动阶段的 Base.metadata.create_all 负责；此处升级已有业务库。
    if "training_tasks" not in existing:
        return

    if "training_questions" not in existing:
        op.create_table(
            "training_questions",
            sa.Column("task_id", sa.Integer(), nullable=False),
            sa.Column("code", sa.String(length=64), nullable=False),
            sa.Column("stem", sa.Text(), nullable=False),
            sa.Column("ability_key", sa.String(length=64), nullable=False),
            sa.Column("knowledge_point", sa.String(length=128), nullable=False),
            sa.Column("explanation", sa.Text(), nullable=False),
            sa.Column("sort_order", sa.Integer(), nullable=False),
            sa.Column("max_score", sa.Integer(), nullable=False),
            sa.Column("active", sa.Boolean(), nullable=False),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["task_id"], ["training_tasks.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("task_id", "code", name="uq_training_question_task_code"),
        )
        op.create_index("ix_training_questions_task_id", "training_questions", ["task_id"])
        op.create_index("ix_training_questions_sort_order", "training_questions", ["sort_order"])
        op.create_index("ix_training_questions_active", "training_questions", ["active"])

    if "training_options" not in existing:
        op.create_table(
            "training_options",
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("option_key", sa.String(length=8), nullable=False),
            sa.Column("content", sa.Text(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("feedback", sa.Text(), nullable=False),
            sa.Column("is_correct", sa.Boolean(), nullable=False),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["question_id"], ["training_questions.id"], ondelete="CASCADE"),
            sa.UniqueConstraint("question_id", "option_key", name="uq_training_option_question_key"),
        )
        op.create_index("ix_training_options_question_id", "training_options", ["question_id"])

    if "training_choice_answers" not in existing:
        op.create_table(
            "training_choice_answers",
            sa.Column("session_id", sa.Integer(), nullable=False),
            sa.Column("question_id", sa.Integer(), nullable=False),
            sa.Column("option_id", sa.Integer(), nullable=False),
            sa.Column("score", sa.Integer(), nullable=False),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["session_id"], ["training_sessions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["question_id"], ["training_questions.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["option_id"], ["training_options.id"], ondelete="RESTRICT"),
            sa.UniqueConstraint("session_id", "question_id", name="uq_training_choice_session_question"),
        )
        op.create_index("ix_training_choice_answers_session_id", "training_choice_answers", ["session_id"])
        op.create_index("ix_training_choice_answers_question_id", "training_choice_answers", ["question_id"])
        op.create_index("ix_training_choice_answers_option_id", "training_choice_answers", ["option_id"])

    if "users" in existing and "teaching_plans" not in existing:
        op.create_table(
            "teaching_plans",
            sa.Column("teacher_id", sa.Integer(), nullable=False),
            sa.Column("title", sa.String(length=200), nullable=False),
            sa.Column("class_name", sa.String(length=64), nullable=False),
            sa.Column("status", sa.String(length=32), nullable=False),
            sa.Column("analysis_snapshot", sa.JSON(), nullable=False),
            sa.Column("actions", sa.JSON(), nullable=False),
            sa.Column("notes", sa.Text(), nullable=False),
            sa.Column("generated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("id", sa.Integer(), primary_key=True),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["teacher_id"], ["users.id"], ondelete="CASCADE"),
        )
        op.create_index("ix_teaching_plans_teacher_id", "teaching_plans", ["teacher_id"])
        op.create_index("ix_teaching_plans_class_name", "teaching_plans", ["class_name"])
        op.create_index("ix_teaching_plans_status", "teaching_plans", ["status"])


def downgrade() -> None:
    existing = set(sa.inspect(op.get_bind()).get_table_names())
    for table in ("teaching_plans", "training_choice_answers", "training_options", "training_questions"):
        if table in existing:
            op.drop_table(table)
