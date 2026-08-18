"""安全工具：密码哈希（bcrypt）与 JWT 签发/校验。

直接使用 bcrypt 库，规避 passlib + bcrypt5 的兼容性问题。
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import get_settings

_BCRYPT_MAX = 72  # bcrypt 密码字节上限


def hash_password(raw: str) -> str:
    """返回 bcrypt 哈希（字符串）。"""
    pw = raw.encode("utf-8")[:_BCRYPT_MAX]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(raw: str, hashed: str) -> bool:
    """校验明文与哈希是否匹配。"""
    try:
        return bcrypt.checkpw(raw.encode("utf-8")[:_BCRYPT_MAX], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_access_token(
    subject: str | int,
    role: str,
    extra: dict[str, Any] | None = None,
) -> str:
    """签发 JWT。subject 通常是 user_id。"""
    settings = get_settings()
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "role": role,
        "iat": now,
        "exp": now + timedelta(minutes=settings.jwt_access_token_expire_minutes),
    }
    if extra:
        payload.update(extra)
    return jwt.encode(payload, settings.jwt_secret, algorithm=settings.jwt_algorithm)


def decode_access_token(token: str) -> dict[str, Any]:
    """解码并校验 JWT，失败抛 jwt 异常。"""
    settings = get_settings()
    return jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])


__all__ = ["hash_password", "verify_password", "create_access_token", "decode_access_token"]
