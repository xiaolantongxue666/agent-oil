"""实训相关模型：训练任务、情境、会话、学生作答、评价结果。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.enums import TaskStatus, TrainingStage
from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class TrainingTask(Base, PKMixin, TimestampMixin):
    """训练任务（教学模拟）。"""

    __tablename__ = "training_tasks"

    position_id: Mapped[int | None] = mapped_column(
        ForeignKey("positions.id", ondelete="SET NULL"), nullable=True, index=True
    )
    job_task_id: Mapped[int | None] = mapped_column(
        ForeignKey("job_tasks.id", ondelete="SET NULL"), nullable=True, index=True
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    title: Mapped[str] = mapped_column(String(128))
    description: Mapped[str] = mapped_column(Text, default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=2)  # 1-5
    target_abilities: Mapped[list[Any]] = mapped_column(JSONBType, default=list)  # AbilityKey[]
    knowledge_points: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    required_points: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    reference_points: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    scenario: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    max_follow_ups: Mapped[int] = mapped_column(Integer, default=3)
    estimated_minutes: Mapped[int] = mapped_column(Integer, default=15)
    status: Mapped[TaskStatus] = mapped_column(default=TaskStatus.published)
    created_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)

    sessions: Mapped[list[TrainingSession]] = relationship(back_populates="task")
    questions: Mapped[list[TrainingQuestion]] = relationship(
        back_populates="task", cascade="all, delete-orphan", order_by="TrainingQuestion.sort_order"
    )


class TrainingScenario(Base, PKMixin, TimestampMixin):
    """教学模拟情境（可由 AI 生成，经教师确认）。"""

    __tablename__ = "training_scenarios"

    task_id: Mapped[int] = mapped_column(ForeignKey("training_tasks.id", ondelete="CASCADE"), index=True)
    scenario_text: Mapped[str] = mapped_column(Text, default="")
    conditions: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)  # 模拟工况/参数（教学脱敏）
    ai_generated: Mapped[bool] = mapped_column(Boolean, default=False)
    approved: Mapped[bool] = mapped_column(Boolean, default=True)


class TrainingSession(Base, PKMixin, TimestampMixin):
    """一次实训会话。"""

    __tablename__ = "training_sessions"

    student_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    task_id: Mapped[int] = mapped_column(ForeignKey("training_tasks.id", ondelete="CASCADE"), index=True)
    workflow_instance_id: Mapped[int | None] = mapped_column(
        ForeignKey("workflow_instances.id", ondelete="SET NULL"), nullable=True, index=True
    )
    stage: Mapped[TrainingStage] = mapped_column(default=TrainingStage.init, index=True)
    attempt_count: Mapped[int] = mapped_column(Integer, default=0)
    follow_up_count: Mapped[int] = mapped_column(Integer, default=0)
    max_follow_ups: Mapped[int] = mapped_column(Integer, default=3)
    finished: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    current_coach_question: Mapped[str] = mapped_column(Text, default="")
    question_batch_code: Mapped[str] = mapped_column(String(64), default="", index=True)

    task: Mapped[TrainingTask] = relationship(back_populates="sessions")
    answers: Mapped[list[StudentAnswer]] = relationship(back_populates="session", cascade="all, delete-orphan")
    choice_answers: Mapped[list[TrainingChoiceAnswer]] = relationship(
        back_populates="session", cascade="all, delete-orphan"
    )
    evaluation: Mapped[EvaluationResult | None] = relationship(back_populates="session", uselist=False)


class TrainingQuestion(Base, PKMixin, TimestampMixin):
    """数据驱动的单选实训题。"""

    __tablename__ = "training_questions"
    __table_args__ = (UniqueConstraint("task_id", "code", name="uq_training_question_task_code"),)

    task_id: Mapped[int] = mapped_column(ForeignKey("training_tasks.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(64))
    stem: Mapped[str] = mapped_column(Text)
    ability_key: Mapped[str] = mapped_column(String(64), default="")
    knowledge_point: Mapped[str] = mapped_column(String(128), default="")
    explanation: Mapped[str] = mapped_column(Text, default="")
    sort_order: Mapped[int] = mapped_column(Integer, default=1, index=True)
    max_score: Mapped[int] = mapped_column(Integer, default=100)
    active: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    status: Mapped[str] = mapped_column(String(24), default="published", index=True)
    batch_code: Mapped[str] = mapped_column(String(64), default="seed", index=True)
    generated_by_ai: Mapped[bool] = mapped_column(Boolean, default=False)
    generation_meta: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    task: Mapped[TrainingTask] = relationship(back_populates="questions")
    options: Mapped[list[TrainingOption]] = relationship(
        back_populates="question", cascade="all, delete-orphan", order_by="TrainingOption.option_key"
    )


class TrainingOption(Base, PKMixin, TimestampMixin):
    """实训题选项；score 支持正确、部分正确和风险选项的分级评分。"""

    __tablename__ = "training_options"
    __table_args__ = (UniqueConstraint("question_id", "option_key", name="uq_training_option_question_key"),)

    question_id: Mapped[int] = mapped_column(ForeignKey("training_questions.id", ondelete="CASCADE"), index=True)
    option_key: Mapped[str] = mapped_column(String(8))
    content: Mapped[str] = mapped_column(Text)
    score: Mapped[int] = mapped_column(Integer, default=0)
    feedback: Mapped[str] = mapped_column(Text, default="")
    is_correct: Mapped[bool] = mapped_column(Boolean, default=False)

    question: Mapped[TrainingQuestion] = relationship(back_populates="options")


class TrainingChoiceAnswer(Base, PKMixin, TimestampMixin):
    """学生选择题作答明细，是成绩复核和教师错题分析的数据源。"""

    __tablename__ = "training_choice_answers"
    __table_args__ = (UniqueConstraint("session_id", "question_id", name="uq_training_choice_session_question"),)

    session_id: Mapped[int] = mapped_column(ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True)
    question_id: Mapped[int] = mapped_column(ForeignKey("training_questions.id", ondelete="CASCADE"), index=True)
    option_id: Mapped[int] = mapped_column(ForeignKey("training_options.id", ondelete="RESTRICT"), index=True)
    score: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped[TrainingSession] = relationship(back_populates="choice_answers")
    question: Mapped[TrainingQuestion] = relationship()
    option: Mapped[TrainingOption] = relationship()


class StudentAnswer(Base, PKMixin, TimestampMixin):
    """学生作答记录。"""

    __tablename__ = "student_answers"

    session_id: Mapped[int] = mapped_column(ForeignKey("training_sessions.id", ondelete="CASCADE"), index=True)
    round: Mapped[int] = mapped_column(Integer, default=1)  # 第几轮作答
    content: Mapped[str] = mapped_column(Text)
    is_follow_up: Mapped[bool] = mapped_column(Boolean, default=False)

    session: Mapped[TrainingSession] = relationship(back_populates="answers")


class EvaluationResult(Base, PKMixin, TimestampMixin):
    """混合评价结果。"""

    __tablename__ = "evaluation_results"

    session_id: Mapped[int] = mapped_column(ForeignKey("training_sessions.id", ondelete="CASCADE"), unique=True, index=True)
    final_score: Mapped[float] = mapped_column(Integer, default=0)
    rule_score: Mapped[float] = mapped_column(Integer, default=0)
    semantic_score: Mapped[float] = mapped_column(Integer, default=0)
    llm_score: Mapped[float] = mapped_column(Integer, default=0)
    ability_scores: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    strengths: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    missing_points: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    error_types: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    explanation: Mapped[str] = mapped_column(Text, default="")
    citations: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    next_task_id: Mapped[int | None] = mapped_column(ForeignKey("training_tasks.id", ondelete="SET NULL"), nullable=True)

    session: Mapped[TrainingSession] = relationship(back_populates="evaluation")


class TeachingPlan(Base, PKMixin, TimestampMixin):
    """依据班级实训结果生成的课堂教学实施改进计划，不是专业培养方案。"""

    __tablename__ = "teaching_plans"

    teacher_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    title: Mapped[str] = mapped_column(String(200))
    class_name: Mapped[str] = mapped_column(String(64), default="", index=True)
    status: Mapped[str] = mapped_column(String(32), default="draft", index=True)
    analysis_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    actions: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    notes: Mapped[str] = mapped_column(Text, default="")
    generated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())
