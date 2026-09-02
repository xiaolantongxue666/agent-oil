"""P0-2 操作型仿真实训：行为事件模型。

TrainingActionEvent 是整个仿真实训系统的核心数据：
记录学生"看了什么、什么时候看、顺序是什么、最后判断是什么"，
评分完全由 行为事件 + 状态机 + Rubric 决定（不经 LLM）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin
from app.models.training import TrainingSession


class TrainingActionEvent(Base, PKMixin):
    """仿真实训中的单条学生行为事件（只增不改，作为能力评价证据源）。"""

    __tablename__ = "training_action_events"

    session_id: Mapped[int] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True
    )
    student_id: Mapped[int] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    # 事件类型（VIEW_TREND / MARK_ABNORMAL_POINT / SUBMIT_DIAGNOSIS ...，取值由场景配置约束）
    event_type: Mapped[str] = mapped_column(String(48), index=True)
    # 场景配置中的动作编码（expected_actions/critical_actions 与之对应）
    event_code: Mapped[str] = mapped_column(String(64), default="", index=True)
    # 事件对象（如 device/pump-01、trend/pressure），教学模拟标识
    target_type: Mapped[str] = mapped_column(String(32), default="")
    target_id: Mapped[str] = mapped_column(String(64), default="")
    sequence_no: Mapped[int] = mapped_column(Integer, default=0)  # 会话内序号（后端分配）
    payload_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    ability_key: Mapped[str] = mapped_column(String(64), default="")
    raw_score: Mapped[float] = mapped_column(Float, default=0.0)  # 本事件 rubric 原始得分
    evidence_score: Mapped[float] = mapped_column(Float, default=0.0)  # 折算后的证据分 0-100
    is_expected: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否命中期望动作
    is_critical: Mapped[bool] = mapped_column(Boolean, default=False)  # 是否关键动作
    error_type: Mapped[str] = mapped_column(String(64), default="")  # 错误归因（漏做/选错等）
    occurred_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    session: Mapped[TrainingSession] = relationship(back_populates="action_events")
