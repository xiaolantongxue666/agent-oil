"""add editable prompt templates and revisions

Revision ID: 20260812_02
Revises: 20260812_01
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260812_02"
down_revision: str | None = "20260812_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "prompt_templates" not in tables:
        op.create_table(
            "prompt_templates",
            sa.Column("code", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("category", sa.String(64), nullable=False),
            sa.Column("description", sa.Text(), nullable=False, server_default=""),
            sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("user_prompt_template", sa.Text(), nullable=False, server_default=""),
            sa.Column("variables", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("source_location", sa.String(256), nullable=False, server_default=""),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("updated_by", sa.Integer(), nullable=True),
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("code"),
        )
        op.create_index("ix_prompt_templates_code", "prompt_templates", ["code"], unique=True)
        op.create_index("ix_prompt_templates_category", "prompt_templates", ["category"])
        op.create_index("ix_prompt_templates_is_default", "prompt_templates", ["is_default"])
    if "prompt_template_revisions" not in tables:
        op.create_table(
            "prompt_template_revisions",
            sa.Column("prompt_template_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False),
            sa.Column("system_prompt", sa.Text(), nullable=False, server_default=""),
            sa.Column("user_prompt_template", sa.Text(), nullable=False, server_default=""),
            sa.Column("change_note", sa.String(500), nullable=False, server_default=""),
            sa.Column("is_default", sa.Boolean(), nullable=False, server_default=sa.false()),
            sa.Column("changed_by", sa.Integer(), nullable=True),
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(
                ["prompt_template_id"], ["prompt_templates.id"], ondelete="CASCADE"
            ),
            sa.ForeignKeyConstraint(["changed_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint(
                "prompt_template_id",
                "version",
                name="uq_prompt_template_revision_version",
            ),
        )
        op.create_index(
            "ix_prompt_template_revisions_prompt_template_id",
            "prompt_template_revisions",
            ["prompt_template_id"],
        )


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "prompt_template_revisions" in tables:
        op.drop_table("prompt_template_revisions")
    if "prompt_templates" in tables:
        op.drop_table("prompt_templates")
