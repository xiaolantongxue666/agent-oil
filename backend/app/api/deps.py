"""FastAPI 公共依赖。"""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import decode_access_token
from app.db.session import get_db
from app.models.user import User


async def get_current_user(
    session: Annotated[AsyncSession, Depends(get_db)],
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    """解析令牌，并以数据库中的当前账号状态和角色为准。"""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未提供有效的认证凭据",
        )
    token = authorization.split(" ", 1)[1].strip()
    try:
        payload = decode_access_token(token)
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭据无效或已过期",
        ) from exc
    try:
        user_id = int(payload["sub"])
    except (KeyError, TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="认证凭据无效或已过期",
        ) from exc
    db_user = await session.get(User, user_id)
    if db_user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="账号不存在")
    if not db_user.is_active:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="账号已被禁用")
    role = db_user.role.value if hasattr(db_user.role, "value") else str(db_user.role)
    return {"user_id": str(db_user.id), "role": role}


def require_role(*roles: str):
    """角色守卫工厂。"""

    async def _checker(
        user: Annotated[dict[str, str], Depends(get_current_user)],
    ) -> dict[str, str]:
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="无权限访问该资源",
            )
        return user

    return _checker


DBSession = Annotated[AsyncSession, Depends(get_db)]
CurrentUser = Annotated[dict[str, str], Depends(get_current_user)]
TeacherUser = Annotated[dict[str, str], Depends(require_role("teacher", "admin"))]
StudentUser = Annotated[dict[str, str], Depends(require_role("student"))]


async def get_current_admin(user: CurrentUser, session: DBSession) -> dict[str, str]:
    """严格管理员守卫：令牌角色之外，账号必须仍存在、启用且为 admin。"""
    db_user = await session.get(User, int(user["user_id"]))
    role = db_user.role.value if db_user and hasattr(db_user.role, "value") else (str(db_user.role) if db_user else "")
    if not db_user or not db_user.is_active or role != "admin":
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="需要有效管理员权限")
    return user


AdminUser = Annotated[dict[str, str], Depends(get_current_admin)]
