"""P0-2 operation simulation training: action events, scenario binding, score precision

Revision ID: 20260901_02
Revises: 20260901_01

- 新表 training_action_events（仿真实训行为事件，评分核心数据源）；
- training_sessions 增加 scenario_code（仿真会话绑定场景编码，旧会话默认空串）；
- evaluation_results 四个分数列 Integer → Float（修复小数分被截断的缺陷）；
- PostgreSQL：trainingstage 枚举补充仿真实训新阶段值（SQLite 为 VARCHAR，无需处理）。
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import context, op

revision: str = "20260901_02"
down_revision: str | None = "20260901_01"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# 仿真实训新增阶段（core.enums.TrainingStage 同步维护）
_NEW_STAGE_VALUES: tuple[str, ...] = (
    "briefing",
    "observe",
    "diagnose",
    "risk_assess",
    "decision",
    "record",
)

_SCORE_COLUMNS: tuple[str, ...] = ("final_score", "rule_score", "semantic_score", "llm_score")


def _json() -> sa.JSON:
    return sa.JSON().with_variant(postgresql.JSONB(), "postgresql")


def _create_action_events() -> None:
    op.create_table(
        "training_action_events",
        sa.Column("session_id", sa.Integer(), nullable=False),
        sa.Column("student_id", sa.Integer(), nullable=False),
        sa.Column("event_type", sa.String(48), nullable=False),
        sa.Column("event_code", sa.String(64), nullable=False, server_default=""),
        sa.Column("target_type", sa.String(32), nullable=False, server_default=""),
        sa.Column("target_id", sa.String(64), nullable=False, server_default=""),
        sa.Column("sequence_no", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("payload_json", _json(), nullable=False, server_default="{}"),
        sa.Column("ability_key", sa.String(64), nullable=False, server_default=""),
        sa.Column("raw_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("evidence_score", sa.Float(), nullable=False, server_default="0"),
        sa.Column("is_expected", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_critical", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("error_type", sa.String(64), nullable=False, server_default=""),
        sa.Column(
            "occurred_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.ForeignKeyConstraint(["session_id"], ["training_sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["student_id"], ["users.id"], ondelete="CASCADE"),
    )
    for name, columns in (
        ("ix_training_action_events_session_id", ["session_id"]),
        ("ix_training_action_events_student_id", ["student_id"]),
        ("ix_training_action_events_event_type", ["event_type"]),
        ("ix_training_action_events_event_code", ["event_code"]),
    ):
        op.create_index(name, "training_action_events", columns)


def _widen_stage_enum() -> None:
    """PostgreSQL 原生枚举需显式加值；SQLite 为 VARCHAR（无 CHECK）天然兼容。"""
    bind = op.get_bind()
    if bind.dialect.name != "postgresql":
        return
    existing = {
        row[0]
        for row in bind.exec_driver_sql(
            "SELECT t.typname FROM pg_type t WHERE t.typname = 'trainingstage'"
        )
    }
    if "trainingstage" not in existing:
        return  # 表尚未创建（全新库由 create_all/后续迁移定义完整枚举）
    for value in _NEW_STAGE_VALUES:
        op.execute(
            sa.text(f"ALTER TYPE trainingstage ADD VALUE IF NOT EXISTS '{value}'")
        )


def upgrade() -> None:
    if context.is_offline_mode():
        _create_action_events()
        op.add_column(
            "training_sessions",
            sa.Column("scenario_code", sa.String(64), nullable=False, server_default=""),
        )
        op.create_index(
            "ix_training_sessions_scenario_code", "training_sessions", ["scenario_code"]
        )
        return

    _widen_stage_enum()

    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    if "training_action_events" not in tables:
        _create_action_events()

    if "training_sessions" in tables:
        existing = {item["name"] for item in inspector.get_columns("training_sessions")}
        if "scenario_code" not in existing:
            with op.batch_alter_table("training_sessions") as batch:
                batch.add_column(
                    sa.Column("scenario_code", sa.String(64), nullable=False, server_default="")
                )
            op.create_index(
                "ix_training_sessions_scenario_code",
                "training_sessions",
                ["scenario_code"],
            )

    if "evaluation_results" in tables:
        score_cols = {
            item["name"]: item["type"]
            for item in inspector.get_columns("evaluation_results")
            if item["name"] in _SCORE_COLUMNS
        }
        needs_fix = any(isinstance(t, sa.Integer) for t in score_cols.values())
        if needs_fix:
            with op.batch_alter_table("evaluation_results") as batch:
                for name in _SCORE_COLUMNS:
                    if name in score_cols and isinstance(score_cols[name], sa.Integer):
                        batch.alter_column(name, type_=sa.Float(), existing_nullable=True)


def downgrade() -> None:
    bind = op.get_bind()
    inspector = sa.inspect(bind)
    tables = set(inspector.get_table_names())

    # 分数列类型与枚举加值不回滚（PG 不支持 DROP VALUE，且历史数据精度不回退）
    if "training_sessions" in tables:
        existing = {item["name"] for item in inspector.get_columns("training_sessions")}
        if "scenario_code" in existing:
            op.drop_index("ix_training_sessions_scenario_code", table_name="training_sessions")
            op.drop_column("training_sessions", "scenario_code")

    if "training_action_events" in tables:
        for name in (
            "ix_training_action_events_event_code",
            "ix_training_action_events_event_type",
            "ix_training_action_events_student_id",
            "ix_training_action_events_session_id",
        ):
            op.drop_index(name, table_name="training_action_events")
        op.drop_table("training_action_events")
