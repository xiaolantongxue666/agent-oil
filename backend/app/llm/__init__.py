"""LLM 网关包（第三十一节）。

公开接口：
- get_gateway() -> LLMGateway  单例入口
- LLMGateway.chat / chat_structured / health
- LLMMessage / LLMResponse / StructuredOutputResult
- 异常类

约束：仅本包内实例化 OpenAI Client；API Key 不外泄。
"""

from __future__ import annotations

from app.llm.base import (
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMStructuredOutputError,
    LLMTimeoutError,
    LLMUnavailableError,
    StructuredOutputResult,
)
from app.llm.gateway import LLMGateway, get_gateway, reset_gateway

__all__ = [
    "get_gateway",
    "reset_gateway",
    "LLMGateway",
    "LLMMessage",
    "LLMResponse",
    "StructuredOutputResult",
    "LLMProvider",
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMUnavailableError",
    "LLMStructuredOutputError",
]
