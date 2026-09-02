"""add ability evidence model and evidence-driven profile columns

Revision ID: 20260901_01
Revises: 20260830_01

P0-1 能力评价重构：
- 新表 ability_evidences（统一能力证据）；
- ability_scores 扩展 growth_xp / confidence / evidence_count /
  evidence_type_count / last_evaluated_at（全部带默认值，兼容旧数据）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260901_01"
down_revision: str | None = "20260830_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


_SCORE_COLUMNS: tuple[sa.Column, ...] = (
    sa.Column("growth_xp", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("confidence", sa.String(8), nullable=False, server_default="low"),
    sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("evidence_type_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("last_evaluated_at", sa.DateTime(timezone=True), nullable=True),
)


def _create_ability_evidences() -> None:
    op.create_table(
        "ability_evidences",
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("ability_key", sa.String(64), nullable=False),
        sa.Column("source_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("raw_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("difficulty_weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("recency_weight", sa.Float(), nullable=False, server_default="1"),
        sa.Column("final_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metadata_json", _json(), nullable=False, server_default="{}"),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
    )
    for name, columns in (
        ("ix_ability_evidences_student_id", ["student_id"]),
        ("ix_ability_evidences_ability_key", ["ability_key"]),
        ("ix_ability_evidences_source_type", ["source_type"]),
        ("ix_ability_evidences_source_id", ["source_id"]),
    ):
        op.create_index(name, "ability_evidences", columns)


def upgrade() -> None:
    if context.is_offline_mode():
        _create_ability_evidences()
        for column in _SCORE_COLUMNS:
            op.add_column("ability_scores", column)
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "ability_evidences" not in tables:
        _create_ability_evidences()

    if "ability_scores" in tables:
        existing = {item["name"] for item in inspector.get_columns("ability_scores")}
        for column in _SCORE_COLUMNS:
            if column.name not in existing:
                op.add_column("ability_scores", column)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "ability_scores" in tables:
        existing = {item["name"] for item in inspector.get_columns("ability_scores")}
        for column in reversed(_SCORE_COLUMNS):
            if column.name in existing:
                op.drop_column("ability_scores", column.name)

    if "ability_evidences" in tables:
        op.drop_index("ix_ability_evidences_source_id", table_name="ability_evidences")
        op.drop_index("ix_ability_evidences_source_type", table_name="ability_evidences")
        op.drop_index("ix_ability_evidences_ability_key", table_name="ability_evidences")
        op.drop_index("ix_ability_evidences_student_id", table_name="ability_evidences")
        op.drop_table("ability_evidences")
