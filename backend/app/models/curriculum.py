"""专业培养方案、课程能力映射与产业证据模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class CurriculumProgram(Base, PKMixin, TimestampMixin):
    """一个可追溯的专业人才培养方案版本。"""

    __tablename__ = "curriculum_programs"
    __table_args__ = (
        UniqueConstraint("program_code", "version", name="uq_curriculum_program_version"),
    )

    program_code: Mapped[str] = mapped_column(String(64), index=True)
    major: Mapped[str] = mapped_column(String(128), default="油气储运工程", index=True)
    name: Mapped[str] = mapped_column(String(255))
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="published", index=True)
    objectives: Mapped[str] = mapped_column(Text, default="")
    graduation_requirements: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    source_period_months: Mapped[int] = mapped_column(Integer, default=12)
    change_summary: Mapped[str] = mapped_column(Text, default="")
    parent_program_id: Mapped[int | None] = mapped_column(
        ForeignKey("curriculum_programs.id", ondelete="SET NULL"), nullable=True, index=True
    )
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    courses: Mapped[list[CurriculumCourse]] = relationship(
        back_populates="program", cascade="all, delete-orphan"
    )


class CurriculumCourse(Base, PKMixin, TimestampMixin):
    """方案版本内的一门课程及其岗位能力覆盖。"""

    __tablename__ = "curriculum_courses"
    __table_args__ = (
        UniqueConstraint("program_id", "course_code", name="uq_curriculum_course_code"),
    )

    program_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_programs.id", ondelete="CASCADE"), index=True
    )
    course_code: Mapped[str] = mapped_column(String(64))
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64), default="专业课")
    total_hours: Mapped[int] = mapped_column(Integer, default=0)
    practice_hours: Mapped[int] = mapped_column(Integer, default=0)
    ability_weights: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    knowledge_points: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    position_ids: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    assessment_method: Mapped[str] = mapped_column(String(255), default="过程考核+终结考核")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    sort_order: Mapped[int] = mapped_column(Integer, default=0)

    program: Mapped[CurriculumProgram] = relationship(back_populates="courses")


class IndustryEvidence(Base, PKMixin, TimestampMixin):
    """教师维护的产业政策、标准、企业报告等外部证据。"""

    __tablename__ = "industry_evidence"

    major: Mapped[str] = mapped_column(String(128), default="油气储运工程", index=True)
    title: Mapped[str] = mapped_column(String(255))
    source_name: Mapped[str] = mapped_column(String(255), default="")
    source_type: Mapped[str] = mapped_column(String(32), default="industry_report", index=True)
    source_no: Mapped[str] = mapped_column(String(128), default="", index=True)
    source_url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    summary: Mapped[str] = mapped_column(Text, default="")
    themes: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    skills: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    confidence: Mapped[str] = mapped_column(String(16), default="medium")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class ProgramAdjustmentProposal(Base, PKMixin, TimestampMixin):
    """由产业和岗位证据生成、经教师审核后发布的培养方案调整草案。"""

    __tablename__ = "program_adjustment_proposals"

    base_program_id: Mapped[int] = mapped_column(
        ForeignKey("curriculum_programs.id", ondelete="CASCADE"), index=True
    )
    target_version: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    title: Mapped[str] = mapped_column(String(255))
    analysis_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    actions: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    evidence_refs: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    generation_method: Mapped[str] = mapped_column(String(32), default="evidence_rule")
    review_note: Mapped[str] = mapped_column(Text, default="")
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_program_id: Mapped[int | None] = mapped_column(
        ForeignKey("curriculum_programs.id", ondelete="SET NULL"), nullable=True
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "CurriculumCourse",
    "CurriculumProgram",
    "IndustryEvidence",
    "ProgramAdjustmentProposal",
]
