"""知识库元数据模型（Qdrant Payload 的 PG 侧镜像，见第二十三节）。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import BigInteger, Float, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class KnowledgeItem(Base, PKMixin, TimestampMixin):
    """专业知识条目（教学/脱敏资料，对应 Qdrant 向量点）。"""

    __tablename__ = "knowledge_items"

    knowledge_id: Mapped[str] = mapped_column(String(64), unique=True, index=True)  # 如 HSE-001
    title: Mapped[str] = mapped_column(String(255), default="")
    major: Mapped[str] = mapped_column(String(64), default="油气储运工程", index=True)
    position: Mapped[str] = mapped_column(String(128), default="", index=True)
    job_task: Mapped[str] = mapped_column(String(128), default="")
    ability: Mapped[str] = mapped_column(String(64), default="", index=True)
    knowledge_point: Mapped[str] = mapped_column(String(128), default="")
    skill_point: Mapped[str] = mapped_column(String(128), default="")
    difficulty: Mapped[int] = mapped_column(Integer, default=1)
    content: Mapped[str] = mapped_column(Text, default="")
    source_type: Mapped[str] = mapped_column(String(32), default="", index=True)  # standard/textbook/...
    source_name: Mapped[str] = mapped_column(String(255), default="")
    source_no: Mapped[str] = mapped_column(String(128), default="", index=True)  # 标准/文件编号
    page: Mapped[int | None] = mapped_column(Integer, nullable=True)
    chapter: Mapped[str] = mapped_column(String(128), default="")
    safety_level: Mapped[str] = mapped_column(String(32), default="")
    tags: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(128), nullable=True, index=True)
    chunk_index: Mapped[int] = mapped_column(Integer, default=0)
    vector_embedded: Mapped[bool] = mapped_column(default=False)

    # ---- 文件附件 ----
    file_name: Mapped[str] = mapped_column(String(255), default="")
    file_type: Mapped[str] = mapped_column(String(16), default="")  # pdf/docx/txt/md
    file_size: Mapped[int] = mapped_column(BigInteger, default=0)
    file_hash: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    file_path: Mapped[str] = mapped_column(String(500), default="")  # 本地存档路径，供重新解析/重建索引

    def to_payload(self) -> dict[str, Any]:
        """返回与 Qdrant Payload 一致的字典（第二十三节）。"""
        return {
            "knowledge_id": self.knowledge_id,
            "title": self.title,
            "major": self.major,
            "position": self.position,
            "job_task": self.job_task,
            "ability": self.ability,
            "knowledge_point": self.knowledge_point,
            "skill_point": self.skill_point,
            "difficulty": self.difficulty,
            "content": self.content,
            "source_type": self.source_type,
            "source_name": self.source_name,
            "source_no": self.source_no,
            "page": self.page,
            "chapter": self.chapter,
            "safety_level": self.safety_level,
            "tags": self.tags or [],
            "file_name": self.file_name,
            "file_type": self.file_type,
            "db_id": self.id,
        }


class KnowledgeChunk(Base, PKMixin, TimestampMixin):
    """教师上传文件按章节/条款拆分后的可审核知识块。"""

    __tablename__ = "knowledge_chunks"
    __table_args__ = (
        UniqueConstraint("knowledge_item_id", "chunk_index", name="uq_knowledge_chunk_index"),
    )

    knowledge_item_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    chunk_index: Mapped[int] = mapped_column(Integer)
    heading: Mapped[str] = mapped_column(String(255), default="")
    chapter: Mapped[str] = mapped_column(String(255), default="")
    heading_path: Mapped[str] = mapped_column(String(512), default="")  # 完整标题层级路径
    chunk_type: Mapped[str] = mapped_column(String(16), default="text")  # text | table
    content: Mapped[str] = mapped_column(Text, default="")
    page_start: Mapped[int | None] = mapped_column(Integer, nullable=True)
    page_end: Mapped[int | None] = mapped_column(Integer, nullable=True)
    char_start: Mapped[int] = mapped_column(Integer, default=0)
    char_end: Mapped[int] = mapped_column(Integer, default=0)
    checksum: Mapped[str] = mapped_column(String(64), index=True)

    knowledge_point_id: Mapped[int | None] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="SET NULL"), nullable=True, index=True
    )
    knowledge_point_code: Mapped[str] = mapped_column(String(64), default="")
    knowledge_point_name: Mapped[str] = mapped_column(String(128), default="")
    ability: Mapped[str] = mapped_column(String(64), default="", index=True)
    match_score: Mapped[float] = mapped_column(Float, default=0.0)
    match_reason: Mapped[str] = mapped_column(String(255), default="")

    enabled: Mapped[bool] = mapped_column(default=False, index=True)
    reviewed: Mapped[bool] = mapped_column(default=False, index=True)
    vector_embedded: Mapped[bool] = mapped_column(default=False)
    qdrant_point_id: Mapped[str | None] = mapped_column(String(128), nullable=True)


class KnowledgeEvidenceRelation(Base, PKMixin):
    """岗位图谱知识点与权威知识条目的正式支撑关系。"""

    __tablename__ = "knowledge_evidence_relations"
    __table_args__ = (
        UniqueConstraint("knowledge_point_id", "knowledge_item_id", name="uq_knowledge_evidence"),
    )

    knowledge_point_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_points.id", ondelete="CASCADE"), index=True
    )
    knowledge_item_id: Mapped[int] = mapped_column(
        ForeignKey("knowledge_items.id", ondelete="CASCADE"), index=True
    )
    relation_type: Mapped[str] = mapped_column(String(32), default="supports")
    relevance: Mapped[float] = mapped_column(Float, default=1.0)
