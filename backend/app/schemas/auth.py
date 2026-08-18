"""认证相关 Schema（Pydantic v2）。"""

from __future__ import annotations

from pydantic import BaseModel, Field


class LoginRequest(BaseModel):
    username: str = Field(..., min_length=1, max_length=64)
    password: str = Field(..., min_length=1, max_length=128)


class TokenResponse(BaseModel):
    token: str
    token_type: str = "Bearer"
    user: "UserOut"


class UserOut(BaseModel):
    id: int
    username: str
    real_name: str = ""
    role: str
    student_no: str | None = None
    class_name: str | None = None

    model_config = {"from_attributes": True}


TokenResponse.model_rebuild()

__all__ = ["LoginRequest", "TokenResponse", "UserOut"]
