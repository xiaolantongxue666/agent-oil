"""专业知识问答会话模型。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class ChatSession(Base, PKMixin, TimestampMixin):
    """问答会话（按所有者角色区分：student / teacher / admin）。"""

    __tablename__ = "chat_sessions"

    user_id: Mapped[int] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), index=True)
    owner_role: Mapped[str] = mapped_column(String(16), default="student", index=True)  # 会话归属角色，教师与学生对话分开存储
    title: Mapped[str] = mapped_column(String(128), default="")

    messages: Mapped[list[ChatMessage]] = relationship(back_populates="session", cascade="all, delete-orphan")


class ChatMessage(Base, PKMixin, TimestampMixin):
    """问答消息（含引用）。"""

    __tablename__ = "chat_messages"

    session_id: Mapped[int] = mapped_column(ForeignKey("chat_sessions.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(16))  # user / assistant / system
    content: Mapped[str] = mapped_column(Text)
    citations: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    assistant_meta: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    knowledge_points: Mapped[list[Any]] = mapped_column(JSONBType, default=list)
    safety_tip: Mapped[str] = mapped_column(Text, default="")
    token_count: Mapped[int] = mapped_column(Integer, default=0)

    session: Mapped[ChatSession] = relationship(back_populates="messages")
