"""阿里云百炼（通义千问）Provider（第三十一节）。

OpenAI 兼容协议接入。API Key 严禁出现在日志/异常 message 中：
- 上游 SDK 异常被映射为本模块自定义异常，message 仅含类别，不含 Key。
"""

from __future__ import annotations

from collections.abc import AsyncIterator
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
    from openai import APIConnectionError, APIStatusError, APITimeoutError, RateLimitError
    from openai import AsyncOpenAI

    _OPENAI_AVAILABLE = True
except Exception:  # pragma: no cover - 兜底
    _OPENAI_AVAILABLE = False


def _redact(text: str) -> str:
    """确保异常文本不含 API Key 片段（截断即可，无需逐字匹配）。"""
    if not text:
        return text
    # 仅保留前 200 字符，避免任何潜在敏感串外泄
    return text[:200]


class BailianProvider(LLMProvider):
    """阿里云百炼 LLM 供应者。"""

    name = "bailian"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        temperature: float = 0.2,
        timeout: int = 60,
    ) -> None:
        if not _OPENAI_AVAILABLE:  # pragma: no cover
            raise LLMUnavailableError("openai 包未安装，无法使用 BailianProvider")
        if not api_key:
            raise LLMUnavailableError("缺少 BAILIAN_API_KEY")
        self._model = model
        self._temperature = temperature
        # 全项目唯一实例化 OpenAI Client 的位置
        self._client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url,
            timeout=timeout,
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
        payload = [
            {"role": m.role.value, "content": m.content} for m in messages
        ]
        try:
            kwargs_build: dict[str, Any] = {
                "model": self._model,
                "messages": payload,
                "temperature": temperature if temperature is not None else self._temperature,
            }
            if max_tokens is not None:
                kwargs_build["max_tokens"] = max_tokens
            if timeout is not None:
                kwargs_build["timeout"] = timeout
            if extra_body:
                # 透传 OpenAI 兼容扩展参数（如 qwen3 的 enable_thinking 开关）
                kwargs_build["extra_body"] = extra_body
            resp = await self._client.chat.completions.create(**kwargs_build)
        except APITimeoutError as exc:
            logger.warning("Bailian 调用超时")
            raise LLMTimeoutError(_redact(str(exc))) from exc
        except RateLimitError as exc:
            logger.warning("Bailian 触发限流")
            raise LLMRateLimitError(_redact(str(exc))) from exc
        except APIConnectionError as exc:
            logger.warning("Bailian 连接失败")
            raise LLMUnavailableError(_redact(str(exc))) from exc
        except APIStatusError as exc:
            logger.warning("Bailian 上游状态错误 status={}", exc.status_code)
            # 5xx 视为不可用，4xx 视为调用错误
            if 500 <= exc.status_code < 600:
                raise LLMUnavailableError(_redact(str(exc))) from exc
            raise LLMError(_redact(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bailian 未知异常")
            raise LLMError(_redact(str(exc))) from exc

        choice = resp.choices[0]
        content = choice.message.content or ""
        usage = {}
        if resp.usage:
            usage = {
                "prompt_tokens": resp.usage.prompt_tokens or 0,
                "completion_tokens": resp.usage.completion_tokens or 0,
                "total_tokens": resp.usage.total_tokens or 0,
            }
        return LLMResponse(
            content=content,
            model=getattr(resp, "model", self._model),
            finish_reason=choice.finish_reason or "",
            usage=usage,
            provider=self.name,
        )

    async def health(self) -> bool:
        try:
            resp = await self._client.chat.completions.create(
                model=self._model,
                messages=[{"role": "user", "content": "ping"}],
                max_tokens=1,
                temperature=0,
            )
            return bool(resp and resp.choices)
        except Exception:  # noqa: BLE001
            return False

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
        """流式对话补全（OpenAI 兼容 SSE）。异常映射与 chat 一致。"""
        payload = [{"role": m.role.value, "content": m.content} for m in messages]
        try:
            kwargs_build: dict[str, Any] = {
                "model": self._model,
                "messages": payload,
                "temperature": temperature if temperature is not None else self._temperature,
                "stream": True,
            }
            if max_tokens is not None:
                kwargs_build["max_tokens"] = max_tokens
            if timeout is not None:
                kwargs_build["timeout"] = timeout
            if extra_body:
                kwargs_build["extra_body"] = extra_body
            stream = await self._client.chat.completions.create(**kwargs_build)
        except APITimeoutError as exc:
            logger.warning("Bailian 流式调用超时")
            raise LLMTimeoutError(_redact(str(exc))) from exc
        except RateLimitError as exc:
            logger.warning("Bailian 触发限流")
            raise LLMRateLimitError(_redact(str(exc))) from exc
        except APIConnectionError as exc:
            logger.warning("Bailian 连接失败")
            raise LLMUnavailableError(_redact(str(exc))) from exc
        except APIStatusError as exc:
            logger.warning("Bailian 上游状态错误 status={}", exc.status_code)
            if 500 <= exc.status_code < 600:
                raise LLMUnavailableError(_redact(str(exc))) from exc
            raise LLMError(_redact(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("Bailian 未知异常")
            raise LLMError(_redact(str(exc))) from exc

        try:
            async for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta
                piece = getattr(delta, "content", None)
                if piece:
                    yield piece
        except LLMError:
            raise
        except APITimeoutError as exc:
            logger.warning("Bailian 流式读取超时")
            raise LLMTimeoutError(_redact(str(exc))) from exc
        except RateLimitError as exc:
            logger.warning("Bailian 流式读取限流")
            raise LLMRateLimitError(_redact(str(exc))) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("Bailian 流式读取异常：{}", type(exc).__name__)
            raise LLMUnavailableError(_redact(str(exc))) from exc

    async def aclose(self) -> None:
        await self._client.close()


__all__ = ["BailianProvider"]
