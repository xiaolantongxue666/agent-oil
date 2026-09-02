"""统一能力证据模型（P0-1）。

任何一次可评分行为都先落为一条 AbilityEvidence，再由
AbilityProfileService 按确定性规则（EMA + 权重）折算进能力画像。

设计约定：
- final_score = clamp(raw_score × difficulty_weight, 0, 100)，是证据的"表现分"；
- evidence_weight / recency_weight 不改变表现分，而是决定该证据推动
  Ability Score 的强度：α_eff = min(α_max, α × evidence_weight × recency_weight)；
- source_id 为多态来源 ID（会话 / 题目 / 评价记录等），不建外键；
- 权重数值统一来自 Settings.ability_evidence_weight()，禁止业务代码写死。
"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Float, ForeignKey, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class AbilityEvidence(Base, PKMixin, TimestampMixin):
    """学生单条能力证据（一个来源行为 → 一个 ability_key）。"""

    __tablename__ = "ability_evidences"

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    ability_key: Mapped[str] = mapped_column(String(64), index=True)

    source_type: Mapped[str] = mapped_column(String(32), index=True)
    source_id: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)

    raw_score: Mapped[float] = mapped_column(Float, default=0.0)
    evidence_weight: Mapped[float] = mapped_column(Float, default=1.0)
    difficulty_weight: Mapped[float] = mapped_column(Float, default=1.0)
    recency_weight: Mapped[float] = mapped_column(Float, default=1.0)
    final_score: Mapped[float] = mapped_column(Float, default=0.0)

    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)


__all__ = ["AbilityEvidence"]
