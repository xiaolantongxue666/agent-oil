"""add curriculum versions and industry evidence

Revision ID: 20260812_03
Revises: 20260812_02
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20260812_03"
down_revision: str | None = "20260812_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "curriculum_programs" not in tables:
        op.create_table(
            "curriculum_programs",
            sa.Column("program_code", sa.String(64), nullable=False),
            sa.Column("major", sa.String(128), nullable=False, server_default="油气储运工程"),
            sa.Column("name", sa.String(255), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(24), nullable=False, server_default="published"),
            sa.Column("objectives", sa.Text(), nullable=False, server_default=""),
            sa.Column("graduation_requirements", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("source_period_months", sa.Integer(), nullable=False, server_default="12"),
            sa.Column("change_summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("parent_program_id", sa.Integer(), nullable=True),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["parent_program_id"], ["curriculum_programs.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("program_code", "version", name="uq_curriculum_program_version"),
        )
        op.create_index("ix_curriculum_programs_program_code", "curriculum_programs", ["program_code"])
        op.create_index("ix_curriculum_programs_major", "curriculum_programs", ["major"])
        op.create_index("ix_curriculum_programs_status", "curriculum_programs", ["status"])
        op.create_index("ix_curriculum_programs_parent_program_id", "curriculum_programs", ["parent_program_id"])
    if "curriculum_courses" not in tables:
        op.create_table(
            "curriculum_courses",
            sa.Column("program_id", sa.Integer(), nullable=False),
            sa.Column("course_code", sa.String(64), nullable=False),
            sa.Column("name", sa.String(128), nullable=False),
            sa.Column("category", sa.String(64), nullable=False, server_default="专业课"),
            sa.Column("total_hours", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("practice_hours", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("ability_weights", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("knowledge_points", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("position_ids", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("assessment_method", sa.String(255), nullable=False, server_default="过程考核+终结考核"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("sort_order", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["program_id"], ["curriculum_programs.id"], ondelete="CASCADE"),
            sa.PrimaryKeyConstraint("id"),
            sa.UniqueConstraint("program_id", "course_code", name="uq_curriculum_course_code"),
        )
        op.create_index("ix_curriculum_courses_program_id", "curriculum_courses", ["program_id"])
        op.create_index("ix_curriculum_courses_enabled", "curriculum_courses", ["enabled"])
    if "industry_evidence" not in tables:
        op.create_table(
            "industry_evidence",
            sa.Column("major", sa.String(128), nullable=False, server_default="油气储运工程"),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("source_name", sa.String(255), nullable=False, server_default=""),
            sa.Column("source_type", sa.String(32), nullable=False, server_default="industry_report"),
            sa.Column("source_no", sa.String(128), nullable=False, server_default=""),
            sa.Column("source_url", sa.Text(), nullable=False, server_default=""),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("summary", sa.Text(), nullable=False, server_default=""),
            sa.Column("themes", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("skills", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("confidence", sa.String(16), nullable=False, server_default="medium"),
            sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_industry_evidence_major", "industry_evidence", ["major"])
        op.create_index("ix_industry_evidence_source_type", "industry_evidence", ["source_type"])
        op.create_index("ix_industry_evidence_source_no", "industry_evidence", ["source_no"])
        op.create_index("ix_industry_evidence_enabled", "industry_evidence", ["enabled"])
    if "program_adjustment_proposals" not in tables:
        op.create_table(
            "program_adjustment_proposals",
            sa.Column("base_program_id", sa.Integer(), nullable=False),
            sa.Column("target_version", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
            sa.Column("title", sa.String(255), nullable=False),
            sa.Column("analysis_snapshot", sa.JSON(), nullable=False, server_default="{}"),
            sa.Column("actions", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("evidence_refs", sa.JSON(), nullable=False, server_default="[]"),
            sa.Column("generation_method", sa.String(32), nullable=False, server_default="evidence_rule"),
            sa.Column("review_note", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_by", sa.Integer(), nullable=True),
            sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("published_program_id", sa.Integer(), nullable=True),
            sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
            sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
            sa.ForeignKeyConstraint(["base_program_id"], ["curriculum_programs.id"], ondelete="CASCADE"),
            sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
            sa.ForeignKeyConstraint(["published_program_id"], ["curriculum_programs.id"], ondelete="SET NULL"),
            sa.PrimaryKeyConstraint("id"),
        )
        op.create_index("ix_program_adjustment_proposals_base_program_id", "program_adjustment_proposals", ["base_program_id"])
        op.create_index("ix_program_adjustment_proposals_status", "program_adjustment_proposals", ["status"])


def downgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    for table in (
        "program_adjustment_proposals",
        "industry_evidence",
        "curriculum_courses",
        "curriculum_programs",
    ):
        if table in tables:
            op.drop_table(table)
