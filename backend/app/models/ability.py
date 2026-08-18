"""能力画像、历史、错误记录、推荐模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class AbilityScore(Base, PKMixin, TimestampMixin):
    """学生某能力的当前得分（增量更新，不在此覆盖历史）。"""

    __tablename__ = "ability_scores"
    __table_args__ = (UniqueConstraint("student_id", "ability_id", name="uq_student_ability"),)

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ability_id: Mapped[int] = mapped_column(ForeignKey("abilities.id", ondelete="CASCADE"), index=True)
    score: Mapped[float] = mapped_column(Float, default=0.0)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)


class AbilityHistory(Base, PKMixin):
    """能力变更历史（不得覆盖历史）。"""

    __tablename__ = "ability_histories"

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ability_id: Mapped[int] = mapped_column(ForeignKey("abilities.id", ondelete="CASCADE"), index=True)
    before_score: Mapped[float] = mapped_column(Float, default=0.0)
    training_score: Mapped[float] = mapped_column(Float, default=0.0)
    after_score: Mapped[float] = mapped_column(Float, default=0.0)
    training_session_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class ErrorRecord(Base, PKMixin, TimestampMixin):
    """学生常见错误记录。"""

    __tablename__ = "error_records"

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    session_id: Mapped[int | None] = mapped_column(
        ForeignKey("training_sessions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    ability_id: Mapped[int | None] = mapped_column(ForeignKey("abilities.id", ondelete="SET NULL"), nullable=True)
    error_type: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    severity: Mapped[int] = mapped_column(Integer, default=1)  # 1=一般 2=关键 3=原则


class LearningRecommendation(Base, PKMixin, TimestampMixin):
    """个性化学习推荐。"""

    __tablename__ = "learning_recommendations"

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("training_tasks.id", ondelete="CASCADE"), index=True)
    target_ability: Mapped[str] = mapped_column(String(64), index=True)
    reason_code: Mapped[str] = mapped_column(String(64), default="weak_ability")
    reason_text: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=2)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=15)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    acted_on: Mapped[bool] = mapped_column(Boolean, default=False)
