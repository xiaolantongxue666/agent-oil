"""add admin governance

Revision ID: 20260814_01
Revises: 20260812_03
"""
from __future__ import annotations
from collections.abc import Sequence
import sqlalchemy as sa
from alembic import op

revision: str = "20260814_01"
down_revision: str | None = "20260812_03"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

def upgrade() -> None:
    tables = set(sa.inspect(op.get_bind()).get_table_names())
    if "feature_configs" not in tables:
        op.create_table("feature_configs", sa.Column("key", sa.String(64), nullable=False), sa.Column("enabled", sa.Boolean(), nullable=False, server_default=sa.true()), sa.Column("read_only", sa.Boolean(), nullable=False, server_default=sa.false()), sa.Column("visible_roles", sa.JSON(), nullable=False, server_default="[]"), sa.Column("reason", sa.Text(), nullable=False, server_default=""), sa.Column("version", sa.Integer(), nullable=False, server_default="1"), sa.Column("updated_by", sa.Integer(), nullable=True), sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["updated_by"], ["users.id"], ondelete="SET NULL"))
        op.create_index("ix_feature_configs_key", "feature_configs", ["key"], unique=True)
    if "admin_audit_logs" not in tables:
        op.create_table("admin_audit_logs", sa.Column("actor_id", sa.Integer(), nullable=True), sa.Column("action", sa.String(128), nullable=False), sa.Column("target_type", sa.String(64), nullable=False), sa.Column("target_id", sa.String(128), nullable=False, server_default=""), sa.Column("detail", sa.JSON(), nullable=False, server_default="{}"), sa.Column("id", sa.Integer(), primary_key=True), sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False), sa.ForeignKeyConstraint(["actor_id"], ["users.id"], ondelete="SET NULL"))
        for col in ("actor_id", "action", "target_type"):
            op.create_index(f"ix_admin_audit_logs_{col}", "admin_audit_logs", [col])

def downgrade() -> None:
    for table in ("admin_audit_logs", "feature_configs"):
        if table in set(sa.inspect(op.get_bind()).get_table_names()):
            op.drop_table(table)
