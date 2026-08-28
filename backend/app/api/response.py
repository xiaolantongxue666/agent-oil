"""统一 API 响应封装与异常体系。

正常：{"success": true, "data": {...}}
异常：{"success": false, "code": "...", "message": "...", "request_id": "..."}
"""

from __future__ import annotations

import uuid
from typing import Any

from fastapi import Request
from fastapi.encoders import jsonable_encoder
from fastapi.responses import JSONResponse

from app.core.logging import logger


class AppError(Exception):
    """业务异常基类。"""

    def __init__(self, code: str, message: str, status_code: int = 400) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code


def ok(data: Any = None) -> dict[str, Any]:
    """构造成功响应。"""
    return {"success": True, "data": jsonable_encoder(data)}


def _fail(code: str, message: str, request_id: str | None = None) -> dict[str, Any]:
    """构造失败响应（内部使用）。"""
    return {
        "success": False,
        "code": code,
        "message": message,
        "request_id": request_id or _new_request_id(),
    }


def _new_request_id() -> str:
    return uuid.uuid4().hex


def _get_request_id(request: Request) -> str:
    return request.headers.get("x-request-id") or _new_request_id()


async def app_error_handler(request: Request, exc: AppError) -> JSONResponse:
    rid = _get_request_id(request)
    logger.warning("AppError code={} msg={} rid={}", exc.code, exc.message, rid)
    return JSONResponse(
        status_code=exc.status_code,
        content=_fail(exc.code, exc.message, rid),
    )


async def unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    rid = _get_request_id(request)
    logger.exception("Unhandled exception rid={} path={}", rid, request.url.path)
    return JSONResponse(
        status_code=500,
        content=_fail("INTERNAL_ERROR", "服务内部错误", rid),
    )


__all__ = [
    "AppError",
    "ok",
    "app_error_handler",
    "unhandled_exception_handler",
]
