"""add auditable job posting publication dates

Revision ID: 20260812_01
Revises: 20260811_01
Create Date: 2026-08-12
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "20260812_01"
down_revision: str | None = "20260811_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job_posting_snapshots" not in inspector.get_table_names():
        return
    columns = {column["name"] for column in inspector.get_columns("job_posting_snapshots")}
    additions = (
        ("published_at_raw", sa.String(128), ""),
        ("published_at_source", sa.String(32), ""),
        ("date_confidence", sa.String(16), "low"),
        ("date_parse_reason", sa.Text(), ""),
    )
    for name, type_, default in additions:
        if name not in columns:
            op.add_column(
                "job_posting_snapshots",
                sa.Column(name, type_, nullable=False, server_default=default),
            )
    indexes = {index["name"] for index in sa.inspect(bind).get_indexes("job_posting_snapshots")}
    if "ix_job_posting_snapshots_date_confidence" not in indexes:
        op.create_index(
            "ix_job_posting_snapshots_date_confidence",
            "job_posting_snapshots",
            ["date_confidence"],
        )

    # 旧版发布日期来自“页面任意日期”启发式解析，无法证明是职位发布日期。
    # 保留原值供教师核验，但一律标记为低置信度，严格趋势不会采用。
    op.execute(
        sa.text(
            "UPDATE job_posting_snapshots "
            "SET date_confidence = 'low', "
            "published_at_source = CASE WHEN published_at IS NULL THEN '' ELSE 'legacy_unverified' END, "
            "date_parse_reason = CASE WHEN published_at IS NULL "
            "THEN '未发现可核验的岗位发布日期' "
            "ELSE '旧版任意日期解析结果，需重新核验' END"
        )
    )


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    if "job_posting_snapshots" not in inspector.get_table_names():
        return
    indexes = {index["name"] for index in inspector.get_indexes("job_posting_snapshots")}
    if "ix_job_posting_snapshots_date_confidence" in indexes:
        op.drop_index("ix_job_posting_snapshots_date_confidence", table_name="job_posting_snapshots")
    columns = {column["name"] for column in inspector.get_columns("job_posting_snapshots")}
    for column in (
        "date_parse_reason",
        "date_confidence",
        "published_at_source",
        "published_at_raw",
    ):
        if column in columns:
            op.drop_column("job_posting_snapshots", column)
