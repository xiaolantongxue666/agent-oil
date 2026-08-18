"""可编辑 LLM Prompt 模板与版本记录。"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class PromptTemplate(Base, PKMixin, TimestampMixin):
    """运行时 Prompt 当前版本。"""

    __tablename__ = "prompt_templates"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    category: Mapped[str] = mapped_column(String(64), index=True)
    description: Mapped[str] = mapped_column(Text, default="")
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    user_prompt_template: Mapped[str] = mapped_column(Text, default="")
    variables: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    source_location: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    is_default: Mapped[bool] = mapped_column(Boolean, default=True, index=True)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


class PromptTemplateRevision(Base, PKMixin, TimestampMixin):
    """Prompt 每次保存或恢复时的不可变版本快照。"""

    __tablename__ = "prompt_template_revisions"
    __table_args__ = (
        UniqueConstraint(
            "prompt_template_id",
            "version",
            name="uq_prompt_template_revision_version",
        ),
    )

    prompt_template_id: Mapped[int] = mapped_column(
        ForeignKey("prompt_templates.id", ondelete="CASCADE"), index=True
    )
    version: Mapped[int] = mapped_column(Integer)
    system_prompt: Mapped[str] = mapped_column(Text, default="")
    user_prompt_template: Mapped[str] = mapped_column(Text, default="")
    change_note: Mapped[str] = mapped_column(String(500), default="")
    is_default: Mapped[bool] = mapped_column(Boolean, default=False)
    changed_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


__all__ = ["PromptTemplate", "PromptTemplateRevision"]
