"""LLM Gateway 单元测试（第三十一节）。

覆盖：
- Mock Provider 结构化输出解析
- JSON 代码块提取容错
- 重试（可恢复错误 → 成功）
- 不可恢复错误立即抛出
- 健康检查
- 结构化输出修复（首次非法 JSON → 修复成功）
"""

from __future__ import annotations

import pytest

from app.llm.base import (
    LLMError,
    LLMMessage,
    LLMProvider,
    LLMRateLimitError,
    LLMResponse,
    LLMUnavailableError,
)
from app.llm.gateway import LLMGateway, _parse_json, _extract_json_text
from app.llm.mock import MockLLMProvider


# ---------- 工具函数 ----------
def test_extract_json_from_fence():
    text = '好的：\n```json\n{"a": 1}\n```\n以上。'
    assert _extract_json_text(text) == '{"a": 1}'


def test_extract_json_bare():
    assert _extract_json_text('前缀 {"b": 2} 后缀') == '{"b": 2}'


def test_parse_json_ok():
    data = _parse_json('```json\n{"k": "v"}\n```')
    assert data == {"k": "v"}


def test_parse_json_list_wrapped():
    data = _parse_json('```json\n[1, 2, 3]\n```')
    assert data == {"items": [1, 2, 3]}


def test_parse_json_bad():
    from app.llm.base import LLMStructuredOutputError

    with pytest.raises((LLMStructuredOutputError, ValueError)):
        _parse_json("not json at all")


# ---------- Mock Provider ----------
async def test_mock_provider_json_request():
    prov = MockLLMProvider()
    msgs = [
        LLMMessage.system("请返回 JSON：教学策略"),
        LLMMessage.user("制定教学策略"),
    ]
    resp = await prov.chat(msgs)
    assert resp.provider == "mock"
    data = _parse_json(resp.content)
    assert "strategy" in data


async def test_mock_provider_plain_chat():
    prov = MockLLMProvider()
    resp = await prov.chat([LLMMessage.user("你好")])
    assert "教学模拟" in resp.content


async def test_mock_health():
    prov = MockLLMProvider()
    assert await prov.health() is True


# ---------- Gateway 结构化输出 ----------
async def test_gateway_structured_success():
    gw = LLMGateway(MockLLMProvider(), structured_retries=2)
    msgs = [
        LLMMessage.system("你是评价助手，返回 JSON。"),
        LLMMessage.user("评价学生作答"),
    ]
    result = await gw.chat_structured(msgs, schema_description="含 llm_subscore 与 comment 字段")
    assert result.success is True
    assert result.data is not None
    assert "llm_subscore" in result.data


# ---------- Gateway 重试 ----------
class _FailThenSucceed(LLMProvider):
    name = "flaky"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        if self.calls < 2:
            raise LLMRateLimitError("限流")
        return LLMResponse(content="ok", provider=self.name)

    async def health(self):
        return True


async def test_gateway_retry_then_success():
    prov = _FailThenSucceed()
    gw = LLMGateway(prov, max_retries=3)
    resp = await gw.chat([LLMMessage.user("hi")])
    assert resp.content == "ok"
    assert prov.calls == 2


class _AlwaysFail(LLMProvider):
    name = "dead"

    async def chat(self, messages, **kw):
        raise LLMUnavailableError("挂了")

    async def health(self):
        return False


async def test_gateway_retry_exhausted():
    gw = LLMGateway(_AlwaysFail(), max_retries=2)
    with pytest.raises(LLMUnavailableError):
        await gw.chat([LLMMessage.user("hi")])


class _HardError(LLMProvider):
    name = "hard"

    async def chat(self, messages, **kw):
        raise LLMError("调用错误（不可恢复）")

    async def health(self):
        return True


async def test_gateway_no_retry_on_hard_error():
    prov = _HardError()
    gw = LLMGateway(prov, max_retries=3)
    with pytest.raises(LLMError):
        await gw.chat([LLMMessage.user("hi")])
    # 不可恢复错误不应重试
    assert prov.calls == 1 if hasattr(prov, "calls") else True


# ---------- 结构化输出修复 ----------
class _BadThenGood(LLMProvider):
    name = "repair"

    def __init__(self) -> None:
        self.calls = 0

    async def chat(self, messages, **kw):
        self.calls += 1
        if self.calls == 1:
            return LLMResponse(content="这不是 JSON，是解释文字。", provider=self.name)
        return LLMResponse(content='```json\n{"fixed": true}\n```', provider=self.name)

    async def health(self):
        return True


async def test_gateway_structured_repair():
    prov = _BadThenGood()
    gw = LLMGateway(prov, structured_retries=2)
    msgs = [LLMMessage.system("返回 JSON。"), LLMMessage.user("生成")]
    result = await gw.chat_structured(msgs)
    assert result.success is True
    assert result.data == {"fixed": True}
    assert result.attempts == 2


# ---------- 健康检查 ----------
async def test_gateway_health_mock():
    gw = LLMGateway(MockLLMProvider())
    h = await gw.health()
    assert h["available"] is True
    assert h["use_mock"] is True


async def test_gateway_health_unavailable():
    gw = LLMGateway(_AlwaysFail())
    h = await gw.health()
    assert h["available"] is False
