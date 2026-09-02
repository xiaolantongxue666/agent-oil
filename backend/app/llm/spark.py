"""讯飞星火 Spark Provider（P1-3，§51~§52）。

星火提供 OpenAI 兼容端点（https://spark-api-open.xf-yun.com/v1），
与 BailianProvider 同构复用 openai SDK；API Key 严禁出现在日志/异常 message 中。
业务代码不感知具体 Provider，切换仅由网关按运行时配置分发。
"""

from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.llm.base import (
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMTimeoutError,
    LLMUnavailableError,
)

try:  # openai 为核心依赖，但测试环境允许缺失（Mock 优先）
    from openai import (
        APIConnectionError,
        APIStatusError,
        APITimeoutError,
        AsyncOpenAI,
        RateLimitError,
    )

    _OPENAI_AVAILABLE = True
except Exception:  # pragma: no cover - 兜底
    _OPENAI_AVAILABLE = False

SPARK_DEFAULT_BASE_URL = "https://spark-api-open.xf-yun.com/v1"


def _redact(text: str) -> str:
    """异常文本截断，避免任何潜在敏感串外泄。"""
    return text[:200] if text else text


class SparkProvider(LLMProvider):
    """讯飞星火 LLM 供应者（OpenAI 兼容协议）。"""

    name = "spark"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str = SPARK_DEFAULT_BASE_URL,
        model: str = "generalv3.5",
        temperature: float = 0.2,
        timeout: int = 60,
    ) -> None:
        if not _OPENAI_AVAILABLE:  # pragma: no cover
            raise LLMUnavailableError("openai 包未安装，无法使用 SparkProvider")
        if not api_key:
            raise LLMUnavailableError("缺少星火 API Key")
        self._model = model
        self._temperature = temperature
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url or SPARK_DEFAULT_BASE_URL,
            timeout=timeout,
            max_retries=0,  # 重试统一由 LLMGateway 负责
        )

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
        try:
            response = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role.value, "content": m.content} for m in messages],
                temperature=self._temperature if temperature is None else temperature,
                max_tokens=max_tokens,
                extra_body=extra_body,
            )
        except APITimeoutError as exc:
            raise LLMTimeoutError("星火请求超时") from exc
        except RateLimitError as exc:
            raise LLMRateLimitError("星火限流") from exc
        except APIConnectionError as exc:
            raise LLMUnavailableError("星火连接失败") from exc
        except APIStatusError as exc:
            raise LLMError(f"星火返回错误状态 {_redact(str(exc))}") from exc
        except Exception as exc:  # noqa: BLE001 - SDK 异常统一映射，不泄漏 Key
            logger.warning("星火调用失败：{}", _redact(str(exc)))
            raise LLMError("星火调用失败") from exc
        choice = response.choices[0] if response.choices else None
        content = (choice.message.content if choice and choice.message else "") or ""
        finish = choice.finish_reason if choice else ""
        usage: dict[str, int] = {}
        resp_usage = getattr(response, "usage", None)
        if resp_usage is not None:
            usage = {
                "prompt_tokens": resp_usage.prompt_tokens or 0,
                "completion_tokens": resp_usage.completion_tokens or 0,
                "total_tokens": resp_usage.total_tokens or 0,
            }
        return LLMResponse(
            content=content,
            model=getattr(response, "model", "") or self._model,
            finish_reason=finish or "",
            usage=usage,
            provider=self.name,
        )

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        extra_body: dict[str, Any] | None = None,
        **_kwargs: Any,
    ):
        """流式对话；SDK 不可用或上游失败时抛出统一异常（网关负责降级）。"""
        if not _OPENAI_AVAILABLE:  # pragma: no cover
            raise LLMUnavailableError("openai 包未安装，无法使用 SparkProvider")
        try:
            stream = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": m.role.value, "content": m.content} for m in messages],
                temperature=self._temperature if temperature is None else temperature,
                max_tokens=max_tokens,
                extra_body=extra_body,
                stream=True,
            )
            async for chunk in stream:
                if chunk.choices and chunk.choices[0].delta and chunk.choices[0].delta.content:
                    yield chunk.choices[0].delta.content
        except (APITimeoutError, RateLimitError, APIConnectionError, APIStatusError) as exc:
            raise LLMError(f"星火流式失败 {_redact(type(exc).__name__)}") from exc

    async def health(self) -> bool:
        """连通性探活：最小请求成功即视为健康。"""
        try:
            await self.chat([LLMMessage(role="user", content="ping")], max_tokens=1, timeout=10)
            return True
        except Exception:  # noqa: BLE001 - 探活不抛
            return False


__all__ = ["SPARK_DEFAULT_BASE_URL", "SparkProvider"]
