"""受约束岗位浏览器 Agent 的安全边界和证据校验测试。"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from app.services.position_browser_agent import (
    BrowserPageState,
    PlaywrightBrowserSession,
    PositionBrowserAgent,
    _assert_allowed,
    _host_allowed,
    _is_attachment_url,
    _looks_like_maintenance,
    final_run_status,
    filter_duplicate_snapshots,
    validate_browser_candidate,
)


def test_browser_allowlist_rejects_external_and_non_http_urls():
    domains = ("zhaopin.cnpc.com.cn", "cnpc.com.cn")

    assert _host_allowed("https://zhaopin.cnpc.com.cn/jobs/1", domains)
    assert _host_allowed("https://news.cnpc.com.cn/recruit/1", domains)
    assert not _host_allowed("https://cnpc.com.cn.example.com/jobs/1", domains)
    assert not _host_allowed("file:///etc/passwd", domains)
    with pytest.raises(ValueError, match="非白名单"):
        _assert_allowed("https://example.com/jobs/1", domains)


def test_candidate_must_be_verifiable_on_original_official_page():
    source = {
        "name": "中国石油高校毕业生招聘平台",
        "domains": ("zhaopin.cnpc.com.cn", "cnpc.com.cn"),
    }
    state = BrowserPageState(
        url="https://zhaopin.cnpc.com.cn/jobs/123",
        title="输气站场运行岗",
        text=(
            "输气站场运行岗 中国石油天然气集团有限公司 新疆 "
            "岗位职责：负责长输天然气管道站场运行、设备巡检和参数记录。"
            "任职要求：油气储运相关专业。发布日期：2026-08-20"
        ),
        html='<meta property="article:published_time" content="2026-08-20">',
    )

    candidate = validate_browser_candidate(
        extracted={
            "title": "输气站场运行岗",
            "company": "中国石油天然气集团有限公司",
            "region": "新疆",
        },
        state=state,
        source=source,
        position_name="长输油气管道站场运行岗位",
        aliases=["输气运行岗"],
        lookback_months=0,
    )

    assert candidate.status == "accepted"
    assert candidate.snapshot is not None
    assert candidate.snapshot["source_url"] == state.url
    assert candidate.snapshot["metadata_json"]["llm_fields_verified_against_page"] is True
    assert candidate.snapshot["published_at_source"] == "meta:article:published_time"


def test_hallucinated_title_is_staged_as_rejected_not_snapshot():
    source = {
        "name": "中国石化人才招聘网",
        "domains": ("job.sinopec.com", "sinopec.com"),
    }
    state = BrowserPageState(
        url="https://job.sinopec.com/jobs/456",
        title="招聘信息",
        text="炼化装置操作工 岗位职责：负责装置操作。任职要求：化工专业。",
        html="<html></html>",
    )

    candidate = validate_browser_candidate(
        extracted={"title": "长输油气管道高级工程师", "company": "", "region": ""},
        state=state,
        source=source,
        position_name="长输油气管道站场运行岗位",
        aliases=[],
        lookback_months=0,
    )

    assert candidate.status == "rejected"
    assert candidate.snapshot is None
    assert any("原页面" in error for error in candidate.errors)


def test_attachment_urls_are_blocked():
    assert _is_attachment_url("https://job.sinopec.com/files/岗位说明.pdf")
    assert _is_attachment_url("https://zhaopin.cnpc.com.cn/download/2026/公告.docx?token=1")
    assert not _is_attachment_url("https://job.sinopec.com/jobs/123")
    assert not _is_attachment_url("https://job.sinopec.com/search?kw=pdf")


def test_maintenance_page_detected_without_confusing_job_duties():
    assert _looks_like_maintenance("系统维护中", "请稍后再试")
    assert _looks_like_maintenance("招聘平台", "网站正在维护，给您带来不便敬请谅解。")
    assert not _looks_like_maintenance("输气站场运行岗", "岗位职责：负责设备维护保养和站场巡检。")


def test_final_run_status_distinguishes_restricted_from_empty():
    restricted = [{"source": "中石化", "status": "access_restricted"}]
    maintenance = [{"source": "中石油", "status": "maintenance"}]
    normal = [{"source": "中石化", "status": "available"}, {"source": "中石油", "status": "empty"}]

    assert final_run_status(3, restricted) == "completed"
    assert final_run_status(0, restricted) == "restricted"
    assert final_run_status(0, maintenance) == "restricted"
    assert final_run_status(0, normal) == "empty"


def test_filter_duplicate_snapshots_by_url_and_content():
    items = [
        {"source_url_hash": "u1", "content_hash": "c1"},
        {"source_url_hash": "u2", "content_hash": "c1"},  # 内容与已有重复
        {"source_url_hash": "u3", "content_hash": "c3"},
        {"source_url_hash": "u3", "content_hash": "c3"},  # 批内重复
        {"source_url_hash": "u4", "content_hash": ""},  # 无内容哈希，仅按 URL 判定
    ]
    fresh, duplicates = filter_duplicate_snapshots(items, {"u1"}, {"c1"})

    assert duplicates == 3
    assert [item["source_url_hash"] for item in fresh] == ["u3", "u4"]


async def test_session_respects_per_domain_interval(monkeypatch):
    sleeps: list[float] = []

    async def fake_sleep(seconds: float) -> None:
        sleeps.append(seconds)

    monkeypatch.setattr(asyncio, "sleep", fake_sleep)
    session = PlaywrightBrowserSession()
    session.min_interval = 2.0
    session._last_navigation_at = {"job.sinopec.com": __import__("time").monotonic()}

    await session._respect_domain_interval("https://job.sinopec.com/jobs/1")
    assert len(sleeps) == 1 and 0 < sleeps[0] <= 2.0

    await session._respect_domain_interval("https://zhaopin.cnpc.com.cn/")
    assert len(sleeps) == 1  # 新域名无需等待


class _FakeGateway:
    def __init__(self) -> None:
        self.calls = 0

    async def chat_structured(self, messages, **kwargs):
        del messages, kwargs
        self.calls += 1
        if self.calls in {1, 3}:
            return SimpleNamespace(success=True, data={"action": "extract"}, error="")
        title = "输气站场运行岗" if self.calls == 2 else "油气管道运行岗"
        return SimpleNamespace(
            success=True,
            data={"items": [{"title": title, "company": "", "region": ""}]},
            error="",
        )


class _FakeBrowser:
    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def goto(self, url, allowed_domains):
        _assert_allowed(url, allowed_domains)
        if "cnpc" in url:
            title = "输气站场运行岗"
        else:
            title = "油气管道运行岗"
        return BrowserPageState(
            url=url,
            title=title,
            text=f"{title} 岗位职责：负责长输油气管道站场运行和设备巡检。任职要求：油气储运专业。",
            html="<html></html>",
        )

    async def snapshot(self, allowed_domains):  # pragma: no cover - fake protocol completeness
        raise AssertionError(allowed_domains)

    async def click(self, ref, allowed_domains):  # pragma: no cover
        raise AssertionError((ref, allowed_domains))

    async def fill(self, ref, value, allowed_domains):  # pragma: no cover
        raise AssertionError((ref, value, allowed_domains))

    async def back(self, allowed_domains):  # pragma: no cover
        raise AssertionError(allowed_domains)


async def test_agent_uses_llm_to_extract_then_rule_layer_builds_snapshots():
    gateway = _FakeGateway()
    agent = PositionBrowserAgent(browser_factory=_FakeBrowser, gateway=gateway)

    result = await agent.discover(
        position_name="长输油气管道站场运行岗位",
        aliases=["输气运行岗"],
        description="",
        max_results=10,
        lookback_months=0,
    )

    assert gateway.calls == 4
    assert len(result.candidates) == 2
    assert len(result.hits) == 2
    assert all(
        item["metadata_json"]["discovery_method"] == "constrained_llm_browser"
        for item in result.hits
    )
