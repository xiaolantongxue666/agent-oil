"""Workflow 持久化模型：实例与执行日志。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class WorkflowInstance(Base, PKMixin, TimestampMixin):
    """Workflow 运行实例（支持中断恢复）。"""

    __tablename__ = "workflow_instances"

    workflow_type: Mapped[str] = mapped_column(String(64), index=True)  # qa / training / task_gen
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    session_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    state: Mapped[str] = mapped_column(String(32), default="PENDING", index=True)  # 见 workflow.enums
    current_node: Mapped[str] = mapped_column(String(64), default="")
    context_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)  # WorkflowContext 快照
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(Text, default="")
    finished: Mapped[bool] = mapped_column(default=False)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class WorkflowExecutionLog(Base, PKMixin):
    """每执行一个 Node 的日志（Debug / 教学流程追踪 / 比赛展示）。"""

    __tablename__ = "workflow_execution_logs"

    workflow_id: Mapped[int] = mapped_column(ForeignKey("workflow_instances.id", ondelete="CASCADE"), index=True)
    node_name: Mapped[str] = mapped_column(String(64), index=True)
    input_summary: Mapped[str] = mapped_column(Text, default="")
    output_summary: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="RUNNING")
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error_type: Mapped[str] = mapped_column(String(64), default="")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
