"""add constrained browser discovery agent

Revision ID: 20260830_01
Revises: 20260824_01
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260830_01"
down_revision: str | None = "20260824_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def upgrade() -> None:
    run_columns = (
        sa.Column("mode", sa.String(24), nullable=False, server_default="fast"),
        sa.Column("stage", sa.String(48), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("stage_stats", _json(), nullable=False, server_default="{}"),
        sa.Column("official_sources", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        sa.Column("diagnostic", sa.Text(), nullable=False, server_default=""),
    )
    if context.is_offline_mode():
        for column in run_columns:
            op.add_column("position_discovery_runs", column)
        op.create_index("ix_position_discovery_runs_mode", "position_discovery_runs", ["mode"])
        _create_candidates()
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "position_discovery_runs" not in tables:
        _create_discovery_runs()
    else:
        existing = {item["name"] for item in inspector.get_columns("position_discovery_runs")}
        for column in run_columns:
            if column.name not in existing:
                op.add_column("position_discovery_runs", column)
        indexes = {item["name"] for item in sa.inspect(bind).get_indexes("position_discovery_runs")}
        if "ix_position_discovery_runs_mode" not in indexes:
            op.create_index("ix_position_discovery_runs_mode", "position_discovery_runs", ["mode"])
    tables = set(sa.inspect(bind).get_table_names())
    if "job_posting_snapshots" not in tables:
        _create_snapshots()
    if "position_analysis_runs" not in tables:
        _create_analysis_runs()
    if "position_discovery_candidates" not in tables:
        _create_candidates()


def _create_discovery_runs() -> None:
    op.create_table(
        "position_discovery_runs",
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False, server_default="running"),
        sa.Column("mode", sa.String(24), nullable=False, server_default="fast"),
        sa.Column("stage", sa.String(48), nullable=False, server_default="queued"),
        sa.Column("progress", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cancel_requested", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("query_terms", _json(), nullable=False, server_default="[]"),
        sa.Column("source_domains", _json(), nullable=False, server_default="[]"),
        sa.Column("stage_stats", _json(), nullable=False, server_default="{}"),
        sa.Column("official_sources", _json(), nullable=False, server_default="[]"),
        sa.Column("warnings", _json(), nullable=False, server_default="[]"),
        sa.Column("diagnostic", sa.Text(), nullable=False, server_default=""),
        sa.Column("found_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_summary", sa.Text(), nullable=False, server_default=""),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_position_discovery_runs_position_id", "position_discovery_runs", ["position_id"])
    op.create_index("ix_position_discovery_runs_status", "position_discovery_runs", ["status"])
    op.create_index("ix_position_discovery_runs_mode", "position_discovery_runs", ["mode"])


def _create_snapshots() -> None:
    op.create_table(
        "job_posting_snapshots",
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("discovery_run_id", sa.Integer(), nullable=False),
        sa.Column("title", sa.String(256), nullable=False, server_default=""),
        sa.Column("company", sa.String(256), nullable=False, server_default=""),
        sa.Column("region", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_url_hash", sa.String(64), nullable=False),
        sa.Column("snippet", sa.Text(), nullable=False, server_default=""),
        sa.Column("content", sa.Text(), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at_raw", sa.String(128), nullable=False, server_default=""),
        sa.Column("published_at_source", sa.String(32), nullable=False, server_default=""),
        sa.Column("date_confidence", sa.String(16), nullable=False, server_default="low"),
        sa.Column("date_parse_reason", sa.Text(), nullable=False, server_default=""),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("skills", _json(), nullable=False, server_default="[]"),
        sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("metadata_json", _json(), nullable=False, server_default="{}"),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["discovery_run_id"], ["position_discovery_runs.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("discovery_run_id", "source_url_hash", name="uq_job_snapshot_run_url"),
    )
    for name, columns in (
        ("ix_job_posting_snapshots_position_id", ["position_id"]),
        ("ix_job_posting_snapshots_discovery_run_id", ["discovery_run_id"]),
        ("ix_job_posting_snapshots_source_url_hash", ["source_url_hash"]),
        ("ix_job_posting_snapshots_content_hash", ["content_hash"]),
        ("ix_job_posting_snapshots_observed_at", ["observed_at"]),
        ("ix_job_posting_snapshots_date_confidence", ["date_confidence"]),
    ):
        op.create_index(name, "job_posting_snapshots", columns)


def _create_analysis_runs() -> None:
    op.create_table(
        "position_analysis_runs",
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
        sa.Column("provider", sa.String(64), nullable=False, server_default=""),
        sa.Column("input_snapshot", _json(), nullable=False, server_default="{}"),
        sa.Column("result_json", _json(), nullable=False, server_default="{}"),
        sa.Column("evidence_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("created_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_by", sa.Integer(), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["reviewed_by"], ["users.id"], ondelete="SET NULL"),
        sa.UniqueConstraint("position_id", "version", name="uq_position_analysis_version"),
    )
    op.create_index("ix_position_analysis_runs_position_id", "position_analysis_runs", ["position_id"])
    op.create_index("ix_position_analysis_runs_status", "position_analysis_runs", ["status"])


def _create_candidates() -> None:
    op.create_table(
        "position_discovery_candidates",
        sa.Column("run_id", sa.Integer(), nullable=False),
        sa.Column("position_id", sa.Integer(), nullable=False),
        sa.Column("source_name", sa.String(128), nullable=False, server_default=""),
        sa.Column("source_url", sa.Text(), nullable=False),
        sa.Column("source_url_hash", sa.String(64), nullable=False),
        sa.Column("extracted_json", _json(), nullable=False, server_default="{}"),
        sa.Column("raw_content", sa.Text(), nullable=False, server_default=""),
        sa.Column("validation_status", sa.String(24), nullable=False, server_default="pending"),
        sa.Column("validation_errors", _json(), nullable=False, server_default="[]"),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0"),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["run_id"], ["position_discovery_runs.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["position_id"], ["positions.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_position_discovery_candidates_run_id", "position_discovery_candidates", ["run_id"])
    op.create_index("ix_position_discovery_candidates_position_id", "position_discovery_candidates", ["position_id"])
    op.create_index("ix_position_discovery_candidates_source_url_hash", "position_discovery_candidates", ["source_url_hash"])
    op.create_index("ix_position_discovery_candidates_validation_status", "position_discovery_candidates", ["validation_status"])


def downgrade() -> None:
    if context.is_offline_mode():
        op.drop_table("position_discovery_candidates")
        for name in ("diagnostic", "warnings", "official_sources", "stage_stats", "cancel_requested", "progress", "stage", "mode"):
            op.drop_column("position_discovery_runs", name)
        return
    bind = op.get_bind()
    tables = set(sa.inspect(bind).get_table_names())
    if "position_discovery_candidates" in tables:
        op.drop_table("position_discovery_candidates")
    if "position_discovery_runs" in tables:
        columns = {item["name"] for item in sa.inspect(bind).get_columns("position_discovery_runs")}
        for name in ("diagnostic", "warnings", "official_sources", "stage_stats", "cancel_requested", "progress", "stage", "mode"):
            if name in columns:
                op.drop_column("position_discovery_runs", name)
