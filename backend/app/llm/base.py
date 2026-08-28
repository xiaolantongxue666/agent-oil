"""LLM 网关基础抽象（第三十一节）。

设计原则（强约束）：
- 全项目仅 `app/llm/` 内允许实例化 OpenAI Client。
- LLM 仅做语言推理，返回文本/结构化语言结果；
  严禁决定工作流路由、业务流程、安全校验、数据权限、最终评分、
  能力画像更新、推荐、用户身份与数据持久化。
- API Key 仅存于后端环境变量，不写入日志、不下发前端、不入 Git。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


# ---------- 异常 ----------
class LLMError(Exception):
    """LLM 调用基础异常。"""


class LLMTimeoutError(LLMError):
    """调用超时。"""


class LLMRateLimitError(LLMError):
    """触发限流。"""


class LLMUnavailableError(LLMError):
    """服务不可用（连接失败 / 鉴权失败 / 上游 5xx）。"""


class LLMStructuredOutputError(LLMError):
    """结构化输出解析失败。"""


# ---------- 数据模型 ----------
class LLMRole(str, Enum):
    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"


class LLMMessage(BaseModel):
    """单条消息。content 为纯文本，不含密钥。"""

    role: LLMRole
    content: str

    @classmethod
    def system(cls, content: str) -> "LLMMessage":
        return cls(role=LLMRole.SYSTEM, content=content)

    @classmethod
    def user(cls, content: str) -> "LLMMessage":
        return cls(role=LLMRole.USER, content=content)

    @classmethod
    def assistant(cls, content: str) -> "LLMMessage":
        return cls(role=LLMRole.ASSISTANT, content=content)


class LLMResponse(BaseModel):
    """LLM 调用结果。usage 脱敏（仅 token 计数）。"""

    content: str
    model: str = ""
    finish_reason: str = ""
    usage: dict[str, int] = Field(default_factory=dict)
    provider: str = ""
    raw: dict[str, Any] | None = Field(default=None, exclude=True)


class StructuredOutputResult(BaseModel):
    """结构化输出结果。

    success=True 时 data 为解析后的 dict；
    success=False 时 raw_content/error 供排查。
    """

    success: bool
    data: dict[str, Any] | None = None
    raw_content: str = ""
    error: str = ""
    attempts: int = 0
    provider: str = ""


# ---------- Provider 抽象 ----------
class LLMProvider(ABC):
    """LLM 供应者抽象。"""

    name: str = "base"

    @abstractmethod
    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        extra_body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> LLMResponse:
        """对话补全。"""

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        extra_body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ) -> AsyncIterator[str]:
        """流式对话补全：逐块产出文本片段。

        默认实现回退为非流式调用后一次性产出（子类可覆盖为真流式）。
        """
        resp = await self.chat(
            messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            extra_body=extra_body,
        )
        if resp.content:
            yield resp.content

    @abstractmethod
    async def health(self) -> bool:
        """健康检查（轻量探测）。"""

    async def aclose(self) -> None:
        """释放底层资源。"""
        return None


__all__ = [
    "LLMError",
    "LLMTimeoutError",
    "LLMRateLimitError",
    "LLMUnavailableError",
    "LLMStructuredOutputError",
    "LLMRole",
    "LLMMessage",
    "LLMResponse",
    "StructuredOutputResult",
    "LLMProvider",
]
