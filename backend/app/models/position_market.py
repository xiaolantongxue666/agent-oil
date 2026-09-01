"""教师岗位配置、联网发现和市场需求快照模型。"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import DateTime, Float, ForeignKey, Integer, String, Text, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class PositionDiscoveryRun(Base, PKMixin, TimestampMixin):
    """一次由教师触发的公开招聘数据发现任务。"""

    __tablename__ = "position_discovery_runs"

    position_id: Mapped[int] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), index=True
    )
    status: Mapped[str] = mapped_column(String(24), default="running", index=True)
    mode: Mapped[str] = mapped_column(String(24), default="fast", index=True)
    stage: Mapped[str] = mapped_column(String(48), default="queued")
    progress: Mapped[int] = mapped_column(Integer, default=0)
    cancel_requested: Mapped[bool] = mapped_column(default=False)
    query_terms: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    source_domains: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    stage_stats: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    official_sources: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    warnings: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    diagnostic: Mapped[str] = mapped_column(Text, default="")
    found_count: Mapped[int] = mapped_column(Integer, default=0)
    saved_count: Mapped[int] = mapped_column(Integer, default=0)
    error_summary: Mapped[str] = mapped_column(Text, default="")
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class PositionDiscoveryCandidate(Base, PKMixin, TimestampMixin):
    """浏览器 Agent 抽取的候选；通过规则校验后才复制为正式证据快照。"""

    __tablename__ = "position_discovery_candidates"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("position_discovery_runs.id", ondelete="CASCADE"), index=True
    )
    position_id: Mapped[int] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), index=True
    )
    source_name: Mapped[str] = mapped_column(String(128), default="")
    source_url: Mapped[str] = mapped_column(Text)
    source_url_hash: Mapped[str] = mapped_column(String(64), index=True)
    extracted_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    raw_content: Mapped[str] = mapped_column(Text, default="")
    validation_status: Mapped[str] = mapped_column(String(24), default="pending", index=True)
    validation_errors: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)


class JobPostingSnapshot(Base, PKMixin, TimestampMixin):
    """公开招聘岗位的可追溯快照；不保存求职者个人信息。"""

    __tablename__ = "job_posting_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "discovery_run_id",
            "source_url_hash",
            name="uq_job_snapshot_run_url",
        ),
    )

    position_id: Mapped[int] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), index=True
    )
    discovery_run_id: Mapped[int] = mapped_column(
        ForeignKey("position_discovery_runs.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(256), default="")
    company: Mapped[str] = mapped_column(String(256), default="")
    region: Mapped[str] = mapped_column(String(128), default="")
    source_name: Mapped[str] = mapped_column(String(128), default="")
    source_url: Mapped[str] = mapped_column(Text)
    source_url_hash: Mapped[str] = mapped_column(String(64), index=True)
    snippet: Mapped[str] = mapped_column(Text, default="")
    content: Mapped[str] = mapped_column(Text, default="")
    content_hash: Mapped[str] = mapped_column(String(64), index=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at_raw: Mapped[str] = mapped_column(String(128), default="")
    published_at_source: Mapped[str] = mapped_column(String(32), default="")
    date_confidence: Mapped[str] = mapped_column(String(16), default="low", index=True)
    date_parse_reason: Mapped[str] = mapped_column(Text, default="")
    observed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )
    skills: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    metadata_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)


class PositionAnalysisRun(Base, PKMixin, TimestampMixin):
    """基于招聘证据生成的岗位能力图谱候选版本。"""

    __tablename__ = "position_analysis_runs"
    __table_args__ = (
        UniqueConstraint("position_id", "version", name="uq_position_analysis_version"),
    )

    position_id: Mapped[int] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer, default=1)
    status: Mapped[str] = mapped_column(String(24), default="draft", index=True)
    provider: Mapped[str] = mapped_column(String(64), default="")
    input_snapshot: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    result_json: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    evidence_count: Mapped[int] = mapped_column(Integer, default=0)
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    created_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


__all__ = [
    "JobPostingSnapshot",
    "PositionAnalysisRun",
    "PositionDiscoveryCandidate",
    "PositionDiscoveryRun",
]
