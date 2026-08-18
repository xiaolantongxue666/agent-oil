"""ORM 模型公共 Mixin 与基类工具。

所有模型继承自 app.db.session.Base，并通过 Mixin 复用主键与时间戳。
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import Mapped, mapped_column


class PKMixin:
    """自增主键。"""

    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)


class TimestampMixin:
    """created_at / updated_at。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
