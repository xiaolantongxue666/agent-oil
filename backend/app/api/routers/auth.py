"""认证路由 POST /api/auth/login、GET /api/auth/me。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, status
from sqlalchemy import select

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.core.security import create_access_token, verify_password
from app.models.user import User
from app.schemas.auth import LoginRequest, TokenResponse, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post("/login", summary="用户登录", response_model_exclude_none=True)
async def login(body: LoginRequest, session: DBSession) -> dict:
    stmt = select(User).where(User.username == body.username)
    user = (await session.execute(stmt)).scalar_one_or_none()
    if not user or not verify_password(body.password, user.hashed_password):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if not user.is_active:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="账号已被禁用",
        )
    role = user.role.value if hasattr(user.role, "value") else str(user.role)
    token = create_access_token(subject=user.id, role=role)
    user_out = UserOut.model_validate(
        {
            "id": user.id,
            "username": user.username,
            "real_name": user.real_name,
            "role": role,
            "student_no": user.student_no,
            "class_name": user.class_name,
        }
    )
    return ok(TokenResponse(token=token, user=user_out).model_dump())


@router.get("/me", summary="当前用户信息")
async def me(user: CurrentUser, session: DBSession) -> dict:
    uid = int(user["user_id"])
    stmt = select(User).where(User.id == uid)
    db_user = (await session.execute(stmt)).scalar_one_or_none()
    if not db_user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    role = (
        db_user.role.value
        if hasattr(db_user.role, "value")
        else str(db_user.role)
    )
    return ok(
        UserOut.model_validate(
            {
                "id": db_user.id,
                "username": db_user.username,
                "real_name": db_user.real_name,
                "role": role,
                "student_no": db_user.student_no,
                "class_name": db_user.class_name,
            }
        ).model_dump()
    )


__all__ = ["router"]
