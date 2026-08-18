"""管理员功能开关、不可抵赖的治理审计记录与运行时系统配置。"""

from __future__ import annotations

from typing import Any

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin


class FeatureConfig(Base, PKMixin, TimestampMixin):
    __tablename__ = "feature_configs"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    read_only: Mapped[bool] = mapped_column(Boolean, default=False)
    visible_roles: Mapped[list[str]] = mapped_column(JSONBType, default=list)
    reason: Mapped[str] = mapped_column(Text, default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True)


class AdminAuditLog(Base, PKMixin, TimestampMixin):
    __tablename__ = "admin_audit_logs"

    actor_id: Mapped[int | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"), nullable=True, index=True)
    action: Mapped[str] = mapped_column(String(128), index=True)
    target_type: Mapped[str] = mapped_column(String(64), index=True)
    target_id: Mapped[str] = mapped_column(String(128), default="")
    detail: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)


class SystemSetting(Base, PKMixin, TimestampMixin):
    """运行时可调系统配置（LLM 参数、全局开关等）。

    管理员通过 UI 编辑后即时生效，优先级高于 .env；敏感字段（如 API Key）
    在本简化方案中以明文存储，由审计日志保障可追溯。
    """

    __tablename__ = "system_settings"

    key: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    value: Mapped[str] = mapped_column(Text, default="")
    category: Mapped[str] = mapped_column(String(32), default="llm", index=True)
    description: Mapped[str] = mapped_column(String(256), default="")
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL"), nullable=True
    )


__all__ = ["AdminAuditLog", "FeatureConfig", "SystemSetting"]
