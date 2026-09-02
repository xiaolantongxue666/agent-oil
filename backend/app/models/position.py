"""岗位能力图谱模型。

层级：岗位 Position → 典型工作任务 JobTask → 能力 Ability → 知识点 KnowledgePoint → 技能点 SkillPoint
权重存库，禁止散落硬编码。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, ForeignKey, Float, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin
from app.models.professional_group import Major


class Position(Base, PKMixin, TimestampMixin):
    """岗位（如：油气管道站场运行操作岗位）。"""

    __tablename__ = "positions"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    major: Mapped[str] = mapped_column(String(64), default="油气储运工程")
    # P0-3 兼容列：与 CurriculumProgram.major_id 同步由 seed 回填，专业→岗位链路
    major_id: Mapped[int | None] = mapped_column(
        ForeignKey("majors.id", ondelete="SET NULL"), nullable=True, index=True
    )
    description: Mapped[str] = mapped_column(String(512), default="")
    aliases: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    status: Mapped[str] = mapped_column(String(24), default="published", index=True)
    source_summary: Mapped[str] = mapped_column(Text, default="")
    graph_version: Mapped[int] = mapped_column(Integer, default=1)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    job_tasks: Mapped[list[JobTask]] = relationship(back_populates="position", cascade="all, delete-orphan")
    major_ref: Mapped[Major | None] = relationship("Major")


class Ability(Base, PKMixin, TimestampMixin):
    """六维岗位能力维度（权重存库）。"""

    __tablename__ = "abilities"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(64))
    weight: Mapped[float] = mapped_column(Float, default=0.0)
    description: Mapped[str] = mapped_column(String(256), default="")

    knowledge_points: Mapped[list[KnowledgePoint]] = relationship(back_populates="ability")


class JobTask(Base, PKMixin, TimestampMixin):
    """岗位典型工作任务。"""

    __tablename__ = "job_tasks"

    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    position: Mapped[Position] = relationship(back_populates="job_tasks")
    knowledge_points: Mapped[list[KnowledgePoint]] = relationship(back_populates="job_task")


class KnowledgePoint(Base, PKMixin, TimestampMixin):
    """知识点。"""

    __tablename__ = "knowledge_points"

    ability_id: Mapped[int] = mapped_column(ForeignKey("abilities.id", ondelete="CASCADE"), index=True)
    job_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")

    ability: Mapped[Ability] = relationship(back_populates="knowledge_points")
    job_task: Mapped[JobTask | None] = relationship(back_populates="knowledge_points")
    skill_points: Mapped[list[SkillPoint]] = relationship(back_populates="knowledge_point", cascade="all, delete-orphan")


class SkillPoint(Base, PKMixin, TimestampMixin):
    """技能点。"""

    __tablename__ = "skill_points"

    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64), index=True)
    name: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(String(512), default="")

    knowledge_point: Mapped[KnowledgePoint] = relationship(back_populates="skill_points")


class PositionAbilityRelation(Base, PKMixin):
    """岗位-能力权重（可覆盖默认权重）。"""

    __tablename__ = "position_ability_relations"
    __table_args__ = (UniqueConstraint("position_id", "ability_id", name="uq_position_ability"),)

    position_id: Mapped[int] = mapped_column(ForeignKey("positions.id", ondelete="CASCADE"), index=True)
    ability_id: Mapped[int] = mapped_column(ForeignKey("abilities.id", ondelete="CASCADE"), index=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)


class TaskAbilityRelation(Base, PKMixin):
    """任务-能力映射（任务对某能力的侧重）。"""

    __tablename__ = "task_ability_relations"
    __table_args__ = (UniqueConstraint("job_task_id", "ability_id", name="uq_task_ability"),)

    job_task_id: Mapped[int] = mapped_column(ForeignKey("job_tasks.id", ondelete="CASCADE"), index=True)
    ability_id: Mapped[int] = mapped_column(ForeignKey("abilities.id", ondelete="CASCADE"), index=True)
    weight: Mapped[float] = mapped_column(Float, default=0.0)
