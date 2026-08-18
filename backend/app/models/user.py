"""用户与角色模型。"""

from __future__ import annotations

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column

from app.core.enums import UserRole
from app.db.session import Base
from app.models.base import PKMixin, TimestampMixin


class User(Base, PKMixin, TimestampMixin):
    """系统用户（学生 / 教师 / 管理员）。"""

    __tablename__ = "users"

    username: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    real_name: Mapped[str] = mapped_column(String(64), default="")
    hashed_password: Mapped[str] = mapped_column(String(255))
    role: Mapped[UserRole] = mapped_column(default=UserRole.student, index=True)
    student_no: Mapped[str | None] = mapped_column(String(32), nullable=True)
    class_name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    is_active: Mapped[bool] = mapped_column(default=True)
