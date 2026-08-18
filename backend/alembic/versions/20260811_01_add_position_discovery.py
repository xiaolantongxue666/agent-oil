"""add position discovery and graph drafting

Revision ID: 20260811_01
Revises: 20260810_02
Create Date: 2026-08-11
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260811_01"
down_revision: str | None = "20260810_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "positions" in tables:
        columns = {column["name"] for column in inspector.get_columns("positions")}
        if "aliases" not in columns:
            op.add_column(
                "positions",
                sa.Column("aliases", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            )
        if "status" not in columns:
            op.add_column(
                "positions",
                sa.Column("status", sa.String(24), nullable=False, server_default="published"),
            )
            op.create_index("ix_positions_status", "positions", ["status"])
        if "source_summary" not in columns:
            op.add_column(
                "positions",
                sa.Column("source_summary", sa.Text(), nullable=False, server_default=""),
            )
        if "graph_version" not in columns:
            op.add_column(
                "positions",
                sa.Column("graph_version", sa.Integer(), nullable=False, server_default="1"),
            )
        if "created_by" not in columns:
            op.add_column("positions", sa.Column("created_by", sa.Integer(), nullable=True))
            op.create_index("ix_positions_created_by", "positions", ["created_by"])
            op.create_foreign_key(
                "fk_positions_created_by_users",
                "positions",
                "users",
                ["created_by"],
                ["id"],
                ondelete="SET NULL",
            )
        if "published_at" not in columns:
            op.add_column(
                "positions", sa.Column("published_at", sa.DateTime(timezone=True), nullable=True)
            )

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "position_discovery_runs" not in tables:
        op.create_table(
            "position_discovery_runs",
            sa.Column("position_id", sa.Integer(), nullable=False),
            sa.Column("status", sa.String(24), nullable=False, server_default="running"),
            sa.Column("query_terms", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("source_domains", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
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

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "job_posting_snapshots" not in tables:
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
            sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
            sa.Column("skills", sa.JSON(), nullable=False, server_default=sa.text("'[]'")),
            sa.Column("match_score", sa.Float(), nullable=False, server_default="0"),
            sa.Column("metadata_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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
        ):
            op.create_index(name, "job_posting_snapshots", columns)

    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "position_analysis_runs" not in tables:
        op.create_table(
            "position_analysis_runs",
            sa.Column("position_id", sa.Integer(), nullable=False),
            sa.Column("version", sa.Integer(), nullable=False, server_default="1"),
            sa.Column("status", sa.String(24), nullable=False, server_default="draft"),
            sa.Column("provider", sa.String(64), nullable=False, server_default=""),
            sa.Column("input_snapshot", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
            sa.Column("result_json", sa.JSON(), nullable=False, server_default=sa.text("'{}'")),
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

    inspector = sa.inspect(bind)
    if "training_tasks" in inspector.get_table_names():
        columns = {column["name"] for column in inspector.get_columns("training_tasks")}
        if "position_id" not in columns:
            op.add_column("training_tasks", sa.Column("position_id", sa.Integer(), nullable=True))
            op.create_index("ix_training_tasks_position_id", "training_tasks", ["position_id"])
            op.create_foreign_key(
                "fk_training_tasks_position_id_positions",
                "training_tasks",
                "positions",
                ["position_id"],
                ["id"],
                ondelete="SET NULL",
            )
        if "job_task_id" not in columns:
            op.add_column("training_tasks", sa.Column("job_task_id", sa.Integer(), nullable=True))
            op.create_index("ix_training_tasks_job_task_id", "training_tasks", ["job_task_id"])
            op.create_foreign_key(
                "fk_training_tasks_job_task_id_job_tasks",
                "training_tasks",
                "job_tasks",
                ["job_task_id"],
                ["id"],
                ondelete="SET NULL",
            )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())
    if "training_tasks" in tables:
        columns = {column["name"] for column in inspector.get_columns("training_tasks")}
        if "job_task_id" in columns:
            op.drop_column("training_tasks", "job_task_id")
        if "position_id" in columns:
            op.drop_column("training_tasks", "position_id")
    for table in ("position_analysis_runs", "job_posting_snapshots", "position_discovery_runs"):
        if table in tables:
            op.drop_table(table)
    if "positions" in tables:
        columns = {column["name"] for column in inspector.get_columns("positions")}
        for column in (
            "published_at",
            "created_by",
            "graph_version",
            "source_summary",
            "status",
            "aliases",
        ):
            if column in columns:
                op.drop_column("positions", column)
