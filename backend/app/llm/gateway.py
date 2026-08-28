"""LLM 网关（第三十一节）。

对外唯一入口：业务层只通过 `get_gateway()` 使用 `chat` / `chat_structured` / `health`。
- 依据 Settings 选择 BailianProvider（有 Key 且未开启 Mock）或 MockLLMProvider。
- 自带重试（仅对超时/限流/不可用等可恢复错误）、超时、结构化输出修复。
- 不持有业务上下文，不做路由/评分/持久化——这些由工作流引擎与规则层负责。
"""

from __future__ import annotations

import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.core.config import get_settings
from app.core.logging import logger
from app.llm.bailian import BailianProvider
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
from app.llm.mock import MockLLMProvider
from app.services.prompt_templates import get_prompt_messages

# 可恢复错误（值得重试）
_RETRIABLE = (LLMTimeoutError, LLMRateLimitError, LLMUnavailableError)

# 运行时 LLM 配置（由管理员 UI 写入 DB，启动/保存时加载至内存）。
# 键定义见 _build_provider；为空字符串时回退到 env 的 Settings。
_runtime_llm_config: dict[str, str] = {}

_RUNTIME_KEYS = (
    "llm_provider",      # bailian | mock
    "llm_model",
    "llm_base_url",
    "llm_api_key",
    "llm_temperature",
    "llm_timeout",
    "llm_max_retries",
    "llm_use_mock",
)

_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\}|\[.*\])\s*```", re.DOTALL)
_OBJ_RE = re.compile(r"(\{.*\}|\[.*\])", re.DOTALL)


def _extract_json_text(text: str) -> str:
    """从模型输出中提取 JSON 文本（容忍 ```json 代码块与前后说明文字）。"""
    fence = _FENCE_RE.search(text)
    if fence:
        return fence.group(1)
    obj = _OBJ_RE.search(text)
    if obj:
        return obj.group(1)
    return text.strip()


def _parse_json(text: str) -> dict[str, Any]:
    extracted = _extract_json_text(text)
    data = json.loads(extracted)
    if isinstance(data, list):
        # 列表结构包装为 {"items": [...]}，便于统一 dict 契约
        return {"items": data}
    if not isinstance(data, dict):
        raise LLMStructuredOutputError(f"结构化输出非对象：{type(data).__name__}")
    return data


class LLMGateway:
    """LLM 网关：重试 / 超时 / 结构化修复 / 健康检查。"""

    def __init__(self, provider: LLMProvider, *, max_retries: int = 3, structured_retries: int = 2) -> None:
        self._provider = provider
        self._max_retries = max(1, max_retries)
        self._structured_retries = max(0, structured_retries)

    @property
    def provider_name(self) -> str:
        return self._provider.name

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> LLMResponse:
        """对话补全，带重试。"""
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            try:
                return await self._provider.chat(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    extra_body=extra_body,
                )
            except _RETRIABLE as exc:
                last_exc = exc
                logger.warning(
                    "LLM 调用失败 {}/{}（{}），将重试",
                    attempt, self._max_retries, type(exc).__name__,
                )
                continue
            except LLMError:
                # 非可恢复错误：立即抛出，不重试
                raise
        # 重试耗尽
        raise LLMUnavailableError(f"LLM 重试 {self._max_retries} 次后仍失败") from last_exc

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
    ) -> AsyncIterator[str]:
        """流式对话补全。

        仅当尚未向下游产出任何片段时，才允许对可恢复错误重试；
        一旦开始产出，中途异常直接向上抛出，避免重复内容。
        """
        last_exc: Exception | None = None
        for attempt in range(1, self._max_retries + 1):
            emitted = False
            try:
                async for piece in self._provider.chat_stream(
                    messages,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                ):
                    emitted = True
                    yield piece
                return
            except _RETRIABLE as exc:
                if emitted:
                    raise
                last_exc = exc
                logger.warning(
                    "LLM 流式调用失败 {}/{}（{}），将重试",
                    attempt, self._max_retries, type(exc).__name__,
                )
                continue
            except LLMError:
                # 非可恢复错误：立即抛出，不重试
                raise
        raise LLMUnavailableError(f"LLM 重试 {self._max_retries} 次后仍失败") from last_exc

    async def chat_structured(
        self,
        messages: list[LLMMessage],
        *,
        schema_description: str = "",
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        extra_body: dict[str, Any] | None = None,
    ) -> StructuredOutputResult:
        """要求返回 JSON 的结构化对话，带解析失败修复。

        约束：返回的是"语言推理的结构化结果"，业务方不得直接据此落库/评分；
        须由规则层/混合评分层再加工（见 PHASE 8）。
        """
        working: list[LLMMessage] = list(messages)
        # 字段名契约始终注入：业务提示词即使提到 JSON，也未必约定字段名，
        # 缺失契约会放任模型自选字段名（如 question_text），导致结构校验整批失败。
        if schema_description:
            contract_system, _ = await get_prompt_messages(
                "structured_output_contract",
                {
                    "schema_description": schema_description,
                    "request_context": "",
                },
            )
            working.append(
                LLMMessage.system(contract_system)
            )

        attempts = 0
        last_content = ""
        last_error = ""
        for attempt in range(1, self._structured_retries + 2):
            attempts = attempt
            try:
                resp = await self.chat(
                    working,
                    temperature=temperature,
                    max_tokens=max_tokens,
                    timeout=timeout,
                    extra_body=extra_body,
                )
            except LLMError as exc:
                last_error = str(exc)
                logger.warning("结构化输出第 {} 次调用失败：{}", attempt, last_error)
                continue
            last_content = resp.content
            try:
                data = _parse_json(resp.content)
                return StructuredOutputResult(
                    success=True, data=data, raw_content=resp.content,
                    attempts=attempts, provider=self.provider_name,
                )
            except (LLMStructuredOutputError, json.JSONDecodeError, ValueError) as exc:
                last_error = str(exc)
                logger.warning("结构化输出第 {} 次解析失败：{}", attempt, last_error)
                # 注入修复提示，再试
                repair_system, repair_user = await get_prompt_messages(
                    "structured_output_repair",
                    {
                        "last_error": last_error,
                        "schema_description": schema_description,
                    },
                )
                working = working + [
                    LLMMessage.assistant(resp.content),
                    LLMMessage.system(repair_system),
                    LLMMessage.user(repair_user),
                ]
        return StructuredOutputResult(
            success=False, raw_content=last_content, error=last_error,
            attempts=attempts, provider=self.provider_name,
        )

    async def health(self) -> dict[str, Any]:
        try:
            ok = await self._provider.health()
        except Exception:  # noqa: BLE001
            ok = False
        return {
            "available": bool(ok),
            "provider": self.provider_name,
            "use_mock": self.provider_name == "mock",
        }

    async def aclose(self) -> None:
        await self._provider.aclose()


# ---------- 运行时配置 ----------
async def refresh_runtime_llm_config(session) -> dict[str, str]:
    """从 system_settings 表读取 LLM 配置到模块级内存缓存。

    由应用启动 lifespan 与管理员保存配置时调用；失败时不影响已缓存或 env 回退。
    """
    global _runtime_llm_config
    try:
        from sqlalchemy import select

        from app.models.admin import SystemSetting

        rows = (
            await session.scalars(
                select(SystemSetting).where(SystemSetting.category == "llm")
            )
        ).all()
        _runtime_llm_config = {row.key: row.value for row in rows if row.key in _RUNTIME_KEYS}
        logger.info("运行时 LLM 配置已加载：{} 项", len(_runtime_llm_config))
    except Exception as exc:  # noqa: BLE001
        logger.warning("运行时 LLM 配置加载失败，回退环境变量：{}", exc)
    return dict(_runtime_llm_config)


# ---------- 工厂 ----------
_gateway: LLMGateway | None = None


def _rt(key: str, fallback):
    """读取运行时配置，空值回退到提供的默认值。"""
    value = _runtime_llm_config.get(key, "")
    return value if value != "" else fallback


def _build_provider() -> LLMProvider:
    settings = get_settings()
    use_mock = str(_rt("llm_use_mock", settings.llm_use_mock)).lower() in ("1", "true", "yes")
    api_key = str(_rt("llm_api_key", settings.bailian_api_key))
    base_url = str(_rt("llm_base_url", settings.bailian_base_url))
    model = str(_rt("llm_model", settings.bailian_model))
    temperature_raw = _rt("llm_temperature", settings.bailian_temperature)
    timeout_raw = _rt("llm_timeout", settings.bailian_timeout)
    try:
        temperature = float(temperature_raw)
    except (TypeError, ValueError):
        temperature = settings.bailian_temperature
    try:
        timeout = int(timeout_raw)
    except (TypeError, ValueError):
        timeout = settings.bailian_timeout
    # Mock 优先级：显式开启 mock 或缺少 Key 时使用 Mock
    provider_name = str(_rt("llm_provider", "bailian" if api_key else "mock")).lower()
    force_mock = use_mock or not api_key or provider_name == "mock"
    if not force_mock:
        try:
            return BailianProvider(
                api_key=api_key,
                base_url=base_url,
                model=model,
                temperature=temperature,
                timeout=timeout,
            )
        except LLMUnavailableError as exc:
            logger.warning("BailianProvider 初始化失败，回退 Mock：{}", exc)
    return MockLLMProvider(model="mock-" + model, temperature=temperature)


def get_gateway() -> LLMGateway:
    """返回单例 LLM 网关。"""
    global _gateway
    if _gateway is None:
        settings = get_settings()
        provider = _build_provider()
        max_retries_raw = _rt("llm_max_retries", settings.bailian_max_retries)
        try:
            max_retries = int(max_retries_raw)
        except (TypeError, ValueError):
            max_retries = settings.bailian_max_retries
        _gateway = LLMGateway(
            provider,
            max_retries=max_retries,
            structured_retries=settings.structured_output_max_retries,
        )
        logger.info("LLM 网关已初始化：provider={}", provider.name)
    return _gateway


async def reset_gateway() -> None:
    """释放并重置单例（测试/热更新用）。"""
    global _gateway
    if _gateway is not None:
        await _gateway.aclose()
        _gateway = None


__all__ = [
    "LLMGateway",
    "get_gateway",
    "reset_gateway",
    "refresh_runtime_llm_config",
]
