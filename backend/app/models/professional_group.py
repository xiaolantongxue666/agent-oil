"""专业群数据模型（P0-3 Phase 4）。

层级升级：专业群 → 专业 → 岗位 → 典型工作任务 → 能力 → 课程 → 实训。

- 六维能力体系（app.core.enums.AbilityKey）保持为专业群通用岗位能力底座，
  本模块不重建第二套能力字典；
- 专业特色通过 Major.ability_weights 表达（六维键 → 权重，存库配置，业务代码零硬编码）；
- 既有字符串列（CurriculumProgram.major / Position.major）保留做向后兼容，
  major_id 为新增可选外键，由 seed 按名称精确匹配回填，旧数据不强制迁移。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from sqlalchemy import Boolean, ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.session import Base
from app.db.types import JSONBType
from app.models.base import PKMixin, TimestampMixin

if TYPE_CHECKING:  # 仅类型引用，避免模型层循环导入
    from app.models.curriculum import CurriculumProgram
    from app.models.position import Position


class ProfessionalGroup(Base, PKMixin, TimestampMixin):
    """专业群：若干专业的组织单元（如：智慧油气储运与安全专业群）。"""

    __tablename__ = "professional_groups"

    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128))
    industry_domain: Mapped[str] = mapped_column(String(128), default="", index=True)
    description: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(24), default="published", index=True)

    majors: Mapped[list[Major]] = relationship(
        back_populates="professional_group", cascade="all, delete-orphan"
    )


class Major(Base, PKMixin, TimestampMixin):
    """专业：归属某个专业群；is_core_major 标记群内核心专业。"""

    __tablename__ = "majors"
    __table_args__ = (UniqueConstraint("professional_group_id", "name", name="uq_major_name_in_group"),)

    professional_group_id: Mapped[int] = mapped_column(
        ForeignKey("professional_groups.id", ondelete="CASCADE"), index=True
    )
    code: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    name: Mapped[str] = mapped_column(String(128), index=True)
    is_core_major: Mapped[bool] = mapped_column(Boolean, default=False)
    # 六维能力特色权重：{AbilityKey 值: 权重}，由 seed/教师维护，禁止业务代码写死
    ability_weights: Mapped[dict[str, Any]] = mapped_column(JSONBType, default=dict)
    description: Mapped[str] = mapped_column(String(512), default="")
    status: Mapped[str] = mapped_column(String(24), default="published", index=True)

    professional_group: Mapped[ProfessionalGroup] = relationship(back_populates="majors")
    # 兼容期内按 major_id 关联的既有实体（单向视图，旧数据 major_id 为空则自然缺席）
    # 引号保留：两侧类仅 TYPE_CHECKING 导入，去引号会使 SQLAlchemy 求值失败
    programs: Mapped[list["CurriculumProgram"]] = relationship(  # noqa: UP037
        "CurriculumProgram", foreign_keys="CurriculumProgram.major_id", viewonly=True
    )
    positions: Mapped[list["Position"]] = relationship(  # noqa: UP037
        "Position", foreign_keys="Position.major_id", viewonly=True
    )


__all__ = ["Major", "ProfessionalGroup"]
