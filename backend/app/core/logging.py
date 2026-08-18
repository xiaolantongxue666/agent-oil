"""结构化日志。基于 loguru，统一拦截并屏蔽敏感字段。

不得记录：API Key、用户密码、Authorization Header。
"""

from __future__ import annotations

import sys
from typing import Any

from loguru import logger

from app.core.config import get_settings

_SENSITIVE_KEYS = {
    "api_key",
    "apikey",
    "password",
    "token",
    "authorization",
    "secret",
    "bailian_api_key",
}


def _redact_record(message: Any) -> Any:
    """对日志记录中的敏感字段做脱敏。"""
    if isinstance(message, dict):
        return {
            k: ("***REDACTED***" if k.lower() in _SENSITIVE_KEYS else _redact_record(v))
            for k, v in message.items()
        }
    if isinstance(message, list):
        return [_redact_record(m) for m in message]
    return message


def _patcher(record: Any) -> None:
    record["extra"] = _redact_record(record.get("extra", {}))


def setup_logging() -> None:
    """初始化全局日志配置。应用启动时调用一次。"""
    settings = get_settings()
    logger.remove()
    logger.configure(patcher=_patcher)
    level = "DEBUG" if settings.app_debug else "INFO"
    logger.add(
        sys.stdout,
        level=level,
        serialize=False,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> - "
            "<level>{message}</level>"
        ),
        backtrace=settings.app_debug,
        diagnose=settings.app_debug,
    )


__all__ = ["logger", "setup_logging"]
