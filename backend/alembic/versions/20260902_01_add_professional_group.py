"""P0-3 professional group: professional_groups/majors tables, major_id compatibility columns

Revision ID: 20260902_01
Revises: 20260901_02

- 新表 professional_groups（专业群）与 majors（专业，含六维特色权重 ability_weights）；
- curriculum_programs / positions 增加可空外键 major_id（字符串 major 列保留，向后兼容）；
- 全新库若表尚未创建则跳过建列（由 create_all/基线迁移给出完整结构）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260902_01"
down_revision: str | None = "20260901_02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _json() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _ts_columns() -> list[sa.Column]:
    return [
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
    ]


def _create_professional_groups() -> None:
    op.create_table(
        "professional_groups",
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("industry_domain", sa.String(128), nullable=False, server_default=""),
        sa.Column("description", sa.String(512), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="published"),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        *_ts_columns(),
    )
    op.create_index(
        "ix_professional_groups_code", "professional_groups", ["code"], unique=True
    )
    op.create_index(
        "ix_professional_groups_industry_domain", "professional_groups", ["industry_domain"]
    )
    op.create_index("ix_professional_groups_status", "professional_groups", ["status"])


def _create_majors() -> None:
    op.create_table(
        "majors",
        sa.Column("professional_group_id", sa.Integer(), nullable=False),
        sa.Column("code", sa.String(64), nullable=False),
        sa.Column("name", sa.String(128), nullable=False),
        sa.Column("is_core_major", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("ability_weights", _json(), nullable=False, server_default="{}"),
        sa.Column("description", sa.String(512), nullable=False, server_default=""),
        sa.Column("status", sa.String(24), nullable=False, server_default="published"),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        *_ts_columns(),
        sa.ForeignKeyConstraint(
            ["professional_group_id"], ["professional_groups.id"], ondelete="CASCADE"
        ),
        sa.UniqueConstraint(
            "professional_group_id", "name", name="uq_major_name_in_group"
        ),
    )
    for name, columns, unique in (
        ("ix_majors_professional_group_id", ["professional_group_id"], False),
        ("ix_majors_code", ["code"], True),
        ("ix_majors_name", ["name"], False),
        ("ix_majors_status", ["status"], False),
    ):
        op.create_index(name, "majors", columns, unique=unique)


def _add_major_id_column(table: str) -> None:
    """为既有表补可空外键列。

    SQLite 不支持 ALTER ADD CONSTRAINT，批量(batch)复制重建表以携带外键定义；
    PostgreSQL/MySQL 直接 add_column + create_foreign_key。
    调用方已保证列不存在（upgrade 在线分支做存在性检查）。
    """
    bind = op.get_bind()
    fk_name = f"fk_{table}_majors"
    idx_name = f"ix_{table}_major_id"
    column = sa.Column("major_id", sa.Integer(), nullable=True)
    if bind.dialect.name == "sqlite" and not context.is_offline_mode():
        with op.batch_alter_table(table) as batch:
            batch.add_column(column)
            batch.create_foreign_key(fk_name, "majors", ["major_id"], ["id"], ondelete="SET NULL")
            batch.create_index(idx_name, ["major_id"])
        return
    op.add_column(table, column)
    op.create_foreign_key(fk_name, table, "majors", ["major_id"], ["id"], ondelete="SET NULL")
    op.create_index(idx_name, table, ["major_id"])


def upgrade() -> None:
    if context.is_offline_mode():
        _create_professional_groups()
        _create_majors()
        _add_major_id_column("curriculum_programs")
        _add_major_id_column("positions")
        return

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "professional_groups" not in tables:
        _create_professional_groups()
    if "majors" not in tables:
        # 独立判断：半程失败重跑时 professional_groups 可能已建
        _create_majors()

    for table in ("curriculum_programs", "positions"):
        if table not in tables:
            continue  # 全新库由基线迁移/create_all 提供完整结构
        existing = {item["name"] for item in inspector.get_columns(table)}
        if "major_id" not in existing:
            _add_major_id_column(table)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    for table in ("positions", "curriculum_programs"):
        if table not in tables:
            continue
        existing = {item["name"] for item in inspector.get_columns(table)}
        if "major_id" in existing:
            with op.batch_alter_table(table) as batch:
                batch.drop_index(f"ix_{table}_major_id")
                batch.drop_column("major_id")

    if "majors" in tables:
        op.drop_table("majors")
    if "professional_groups" in tables:
        op.drop_table("professional_groups")
