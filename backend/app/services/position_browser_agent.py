"""受约束的官方招聘站浏览器采集 Agent。

LLM 只在已加载的公开页面上选择动作和抽取字段；域名、页面预算、证据一致性、
岗位相关性及最终落库全部由确定性代码控制。遇验证码或访问限制时立即停止，不绕过。
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass, field
from typing import Any, Protocol
from urllib.parse import urlparse

from app.core.config import get_settings
from app.core.logging import logger
from app.llm import get_gateway
from app.llm.base import LLMMessage
from app.services.position_discovery import (
    _JOB_INDICATORS,
    _clean_text,
    _extract_skills,
    _job_relevant_text,
    _match_score,
    extract_publication_date,
)
from app.services.prompt_templates import get_prompt_messages

_SOURCES: tuple[dict[str, Any], ...] = (
    {
        "key": "cnpc",
        "name": "中国石油高校毕业生招聘平台",
        "start_url": "https://zhaopin.cnpc.com.cn/",
        "domains": ("zhaopin.cnpc.com.cn", "cnpc.com.cn"),
    },
    {
        "key": "sinopec",
        "name": "中国石化人才招聘网",
        "start_url": "https://job.sinopec.com/",
        "domains": ("job.sinopec.com", "sinopec.com"),
    },
)
_BLOCK_MARKERS = (
    "验证码",
    "访问过于频繁",
    "安全验证",
    "access denied",
    "captcha",
    # WAF/网关拦截页（如实测中石油 WAF 返回 502 页面而非 412），必须归入受限而非“正常但为空”
    "502 bad gateway",
    "403 forbidden",
    "您的ip",
    "event id",
    "waf",
)
# 只匹配强特征短语，避免把“负责设备维护”这类岗位职责误判为官网维护。
_MAINTENANCE_MARKERS = (
    "网站正在维护",
    "系统维护中",
    "网站维护公告",
    "站点维护",
    "系统升级中",
    "维护中，请稍后",
    "under maintenance",
    "system maintenance",
)
_DANGEROUS_CLICK_MARKERS = ("申请", "投递", "报名", "登录", "注册", "提交简历", "删除", "支付")
_SEARCH_FIELD_MARKERS = ("搜索", "查询", "关键词", "岗位", "职位", "search", "keyword")
_BLOCKED_RESOURCE_TYPES = {"image", "media", "font"}
_ATTACHMENT_SUFFIXES = (
    ".pdf",
    ".doc",
    ".docx",
    ".docm",
    ".xls",
    ".xlsx",
    ".ppt",
    ".pptx",
    ".zip",
    ".rar",
    ".7z",
    ".tar",
    ".gz",
    ".csv",
)
RESTRICTED_SOURCE_STATUSES = {"access_restricted", "maintenance"}


class BrowserAgentUnavailable(RuntimeError):
    """Playwright 或 Chromium 未安装。"""


class BrowserAgentCancelled(RuntimeError):
    """教师取消采集任务。"""


@dataclass(slots=True)
class BrowserPageState:
    url: str
    title: str
    text: str
    html: str
    controls: list[dict[str, str]] = field(default_factory=list)
    network_json: list[str] = field(default_factory=list)


@dataclass(slots=True)
class CandidateEvaluation:
    source_name: str
    source_url: str
    extracted: dict[str, Any]
    raw_content: str
    status: str
    errors: list[str]
    confidence: float
    snapshot: dict[str, Any] | None = None


@dataclass(slots=True)
class BrowserDiscoveryResult:
    hits: list[dict[str, Any]]
    candidates: list[CandidateEvaluation]
    source_reports: list[dict[str, Any]]
    warnings: list[str]
    stage_stats: dict[str, int]
    diagnostic: str


class BrowserSession(Protocol):
    async def __aenter__(self) -> BrowserSession: ...

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> bool | None: ...

    async def goto(self, url: str, allowed_domains: tuple[str, ...]) -> BrowserPageState: ...

    async def snapshot(self, allowed_domains: tuple[str, ...]) -> BrowserPageState: ...

    async def click(self, ref: str, allowed_domains: tuple[str, ...]) -> BrowserPageState: ...

    async def fill(self, ref: str, value: str, allowed_domains: tuple[str, ...]) -> BrowserPageState: ...

    async def back(self, allowed_domains: tuple[str, ...]) -> BrowserPageState: ...


def _host_allowed(url: str, domains: tuple[str, ...]) -> bool:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    host = parsed.hostname.lower().rstrip(".")
    return any(host == domain or host.endswith(f".{domain}") for domain in domains)


def _assert_allowed(url: str, domains: tuple[str, ...]) -> None:
    if not _host_allowed(url, domains):
        raise ValueError(f"浏览器 Agent 拒绝访问非白名单地址：{url[:200]}")


def _is_attachment_url(url: str) -> bool:
    """按扩展名识别附件下载地址；采集只允许读取网页正文和公开 JSON。"""

    path = urlparse(url).path.lower()
    return path.endswith(_ATTACHMENT_SUFFIXES)


def _looks_like_maintenance(title: str, text: str) -> bool:
    headline = _clean_text(title).lower()
    body = _clean_text(text[:1000]).lower()
    return any(marker in headline or marker in body for marker in _MAINTENANCE_MARKERS)


def final_run_status(hits_count: int, source_reports: list[dict[str, Any]]) -> str:
    """把来源状态折叠为任务终态：有结果 completed，受限 restricted，否则 empty。"""

    if hits_count > 0:
        return "completed"
    if any(str(item.get("status")) in RESTRICTED_SOURCE_STATUSES for item in source_reports):
        return "restricted"
    return "empty"


def filter_duplicate_snapshots(
    items: list[dict[str, Any]],
    existing_url_hashes: set[str],
    existing_content_hashes: set[str],
) -> tuple[list[dict[str, Any]], int]:
    """跨 run 去重：同一岗位下相同 URL 或相同内容的快照不重复入库。"""

    fresh: list[dict[str, Any]] = []
    seen_urls: set[str] = set()
    seen_contents: set[str] = set()
    duplicates = 0
    for item in items:
        url_hash = str(item.get("source_url_hash", ""))
        content_hash = str(item.get("content_hash", ""))
        if (
            url_hash in existing_url_hashes
            or content_hash in existing_content_hashes
            or url_hash in seen_urls
            or (content_hash and content_hash in seen_contents)
        ):
            duplicates += 1
            continue
        seen_urls.add(url_hash)
        if content_hash:
            seen_contents.add(content_hash)
        fresh.append(item)
    return fresh, duplicates


class PlaywrightBrowserSession:
    """Playwright 浏览器工具层；所有导航前后均校验官方域名白名单。"""

    def __init__(self) -> None:
        settings = get_settings()
        self.headless = settings.position_browser_headless
        self.timeout_ms = settings.position_browser_timeout_seconds * 1000
        self.min_interval = max(0.0, float(settings.position_browser_min_interval_seconds))
        self._last_navigation_at: dict[str, float] = {}
        self._playwright: Any = None
        self._browser: Any = None
        self._context: Any = None
        self._page: Any = None
        self._json_payloads: list[str] = []
        self._allowed_domains: tuple[str, ...] = ()

    async def __aenter__(self) -> PlaywrightBrowserSession:
        try:
            from playwright.async_api import async_playwright
        except ImportError as exc:
            raise BrowserAgentUnavailable(
                "未安装 Playwright；请安装后执行 `python -m playwright install chromium`"
            ) from exc
        try:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=self.headless,
                args=["--disable-dev-shm-usage", "--no-sandbox"],
            )
            self._context = await self._browser.new_context(
                locale="zh-CN",
                accept_downloads=False,
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 Chrome/124.0 Safari/537.36 OilTrainSafe/1.0"
                ),
            )
            await self._context.route("**/*", self._route_request)
            self._page = await self._context.new_page()
            self._page.set_default_timeout(self.timeout_ms)
            self._page.on("response", self._capture_response)
            # 官网（如实测中石化公告）常用 window.open 打开详情页，会话必须跟随新标签页
            self._context.on("page", self._adopt_popup)
        except Exception as exc:  # noqa: BLE001
            await self.__aexit__(type(exc), exc, exc.__traceback__)
            raise BrowserAgentUnavailable(f"Chromium 启动失败：{type(exc).__name__}") from exc
        return self

    def _adopt_popup(self, page: Any) -> None:
        """新标签页承载后续导航和抽取；响应捕获同步挂到新页面上。"""

        self._page = page
        page.set_default_timeout(self.timeout_ms)
        page.on("response", self._capture_response)

    def _ensure_page(self) -> None:
        """站点可能自行关闭标签页（如公告页 window.close），回退到仍打开的页面。"""

        if not self._page.is_closed():
            return
        others = [page for page in self._context.pages if not page.is_closed()]
        if not others:
            raise ValueError("浏览器页面已全部关闭，任务终止")
        self._page = others[-1]

    async def _wait_for_content(self) -> None:
        """SPA 首帧常只有页脚（实测中石化首页 t0 仅 61 字 0 控件，入口约 1 秒后才出现）。

        以“正文足够长”或“存在可见可交互元素”为准轮询等待，避免把半渲染页交给模型决策。
        """

        probe = """() => {
          const body = document.body;
          const text = ((body && body.innerText) || '').trim();
          let interactive = 0;
          for (const el of (body ? body.querySelectorAll('a,button,input,[onclick]') : [])) {
            const r = el.getBoundingClientRect();
            const cs = getComputedStyle(el);
            if (r.width && r.height && cs.visibility !== 'hidden' && cs.display !== 'none') interactive += 1;
          }
          if (interactive === 0 && body) {
            const walker = document.createTreeWalker(body, NodeFilter.SHOW_ELEMENT);
            let node, scanned = 0;
            while ((node = walker.nextNode()) && scanned < 1500 && interactive < 3) {
              scanned += 1;
              if (getComputedStyle(node).cursor === 'pointer') interactive += 1;
            }
          }
          return { text: text.length, interactive };
        }"""
        for _ in range(20):
            try:
                state = await self._page.evaluate(probe)
            except Exception:  # noqa: BLE001 - 导航竞态期间页面可能被替换
                return
            if state.get("text", 0) >= 300 or (state.get("text", 0) >= 40 and state.get("interactive", 0) >= 2):
                return
            await self._page.wait_for_timeout(500)

    async def _route_request(self, route: Any) -> None:
        """阻断跨白名单导航/接口、图片媒体资源和附件下载；页面脚本样式可继续加载。"""

        request = route.request
        protected_types = {"document", "xhr", "fetch", "websocket"}
        if (
            request.resource_type in protected_types
            and self._allowed_domains
            and not _host_allowed(request.url, self._allowed_domains)
        ):
            await route.abort("blockedbyclient")
            return
        if request.resource_type in _BLOCKED_RESOURCE_TYPES or _is_attachment_url(request.url):
            await route.abort("blockedbyclient")
            return
        await route.continue_()

    async def _respect_domain_interval(self, url: str) -> None:
        """同一域名两次导航之间至少间隔配置秒数，降低对官方站点的请求压力。"""

        host = (urlparse(url).hostname or "").lower()
        last = self._last_navigation_at.get(host)
        if last is not None and self.min_interval > 0:
            wait = self.min_interval - (time.monotonic() - last)
            if wait > 0:
                await asyncio.sleep(wait)
        self._last_navigation_at[host] = time.monotonic()

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        if self._browser is not None:
            await self._browser.close()
        if self._playwright is not None:
            await self._playwright.stop()

    def _capture_response(self, response: Any) -> None:
        content_type = str(response.headers.get("content-type", "")).lower()
        if (
            "json" not in content_type
            or len(self._json_payloads) >= 20
            or not _host_allowed(response.url, self._allowed_domains)
        ):
            return

        async def read() -> None:
            try:
                text = await response.text()
                if len(text) <= 100_000:
                    self._json_payloads.append(text[:12_000])
            except Exception:  # noqa: BLE001
                return

        asyncio.create_task(read())

    async def goto(self, url: str, allowed_domains: tuple[str, ...]) -> BrowserPageState:
        _assert_allowed(url, allowed_domains)
        self._allowed_domains = allowed_domains
        self._json_payloads.clear()
        await self._respect_domain_interval(url)
        await self._page.goto(url, wait_until="domcontentloaded", timeout=self.timeout_ms)
        return await self.snapshot(allowed_domains)

    async def snapshot(self, allowed_domains: tuple[str, ...]) -> BrowserPageState:
        self._ensure_page()
        await self._wait_for_content()
        await self._page.wait_for_timeout(400)
        _assert_allowed(self._page.url, allowed_domains)
        payload = await self._page.evaluate(
            """() => {
              const collected = [];
              const seen = new Set();
              const consider = (node) => {
                const rect = node.getBoundingClientRect();
                const style = getComputedStyle(node);
                if (!rect.width || !rect.height || style.visibility === 'hidden' || style.display === 'none') return;
                seen.add(node);
                node.setAttribute('data-oil-agent-ref', String(collected.length));
                collected.push(node);
              };
              document.querySelectorAll('a,button,input,textarea,select,[role="button"],[onclick]').forEach(consider);
              // SPA 页面常用 cursor:pointer 的 div 承载点击入口（如中石化首页栏目），补扫这类可点元素
              if (document.body) {
                const walker = document.createTreeWalker(document.body, NodeFilter.SHOW_ELEMENT);
                let node;
                let scanned = 0;
                while ((node = walker.nextNode()) && collected.length < 80 && scanned < 4000) {
                  scanned += 1;
                  if (seen.has(node)) continue;
                  let ancestorCollected = false;
                  for (let p = node.parentElement; p; p = p.parentElement) {
                    if (seen.has(p)) { ancestorCollected = true; break; }
                  }
                  if (ancestorCollected) continue;
                  if (getComputedStyle(node).cursor === 'pointer') consider(node);
                }
              }
              const controls = collected.map((node) => ({
                ref: node.getAttribute('data-oil-agent-ref'),
                tag: node.tagName.toLowerCase(),
                text: (node.innerText || node.value || node.placeholder || node.getAttribute('aria-label') || '').trim().slice(0, 160),
                href: (node.href || '').slice(0, 500),
                type: (node.type || '').slice(0, 40)
              }));
              return { title: document.title, text: (document.body?.innerText || '').slice(0, 30000), controls };
            }"""
        )
        return BrowserPageState(
            url=self._page.url,
            title=str(payload.get("title", ""))[:300],
            text=str(payload.get("text", ""))[:30_000],
            html=(await self._page.content())[:100_000],
            controls=list(payload.get("controls", [])),
            network_json=self._json_payloads[-8:],
        )

    async def click(self, ref: str, allowed_domains: tuple[str, ...]) -> BrowserPageState:
        self._ensure_page()
        locator = self._page.locator(f'[data-oil-agent-ref="{ref}"]')
        if await locator.count() != 1:
            raise ValueError("页面控件已变化，请重新观察后再操作")
        label = _clean_text(
            " ".join(
                str(item or "")
                for item in await locator.evaluate(
                    "node => [node.innerText, node.value, node.getAttribute('aria-label'), node.title]"
                )
            )
        ).lower()
        if any(marker in label for marker in _DANGEROUS_CLICK_MARKERS):
            raise ValueError(f"浏览器 Agent 拒绝可能产生外部状态的操作：{label[:80]}")
        await locator.evaluate("node => node.removeAttribute('target')")
        # 旧页面的 JSON 不再作为新页面证据，也让内容等待不被过期载荷短路
        self._json_payloads.clear()
        await self._respect_domain_interval(self._page.url)
        await locator.click()
        await self._page.wait_for_timeout(800)
        return await self.snapshot(allowed_domains)

    async def fill(self, ref: str, value: str, allowed_domains: tuple[str, ...]) -> BrowserPageState:
        locator = self._page.locator(f'[data-oil-agent-ref="{ref}"]')
        if await locator.count() != 1:
            raise ValueError("页面输入框已变化，请重新观察后再操作")
        field_label = _clean_text(
            " ".join(
                str(item or "")
                for item in await locator.evaluate(
                    "node => [node.placeholder, node.name, node.getAttribute('aria-label'), node.title]"
                )
            )
        ).lower()
        if not any(marker in field_label for marker in _SEARCH_FIELD_MARKERS):
            raise ValueError("浏览器 Agent 只允许填写公开岗位搜索框")
        self._json_payloads.clear()
        await locator.fill(value[:128])
        return await self.snapshot(allowed_domains)

    async def back(self, allowed_domains: tuple[str, ...]) -> BrowserPageState:
        self._ensure_page()
        await self._respect_domain_interval(self._page.url)
        response = await self._page.go_back(wait_until="domcontentloaded")
        if response is None and len(self._context.pages) > 1:
            # 新标签页没有历史可退：关闭它并回到原页面（如公告详情返回列表）
            try:
                await self._page.close()
            except Exception:  # noqa: BLE001 - 页面可能已被站点关闭
                pass
            others = [page for page in self._context.pages if not page.is_closed()]
            if not others:
                raise ValueError("浏览器页面已全部关闭，任务终止")
            self._page = others[-1]
        return await self.snapshot(allowed_domains)


def _contains_untrusted_value(value: str, page_text: str) -> bool:
    value = _clean_text(value).lower()
    page_text = _clean_text(page_text).lower()
    return bool(value) and value in page_text


def validate_browser_candidate(
    *,
    extracted: dict[str, Any],
    state: BrowserPageState,
    source: dict[str, Any],
    position_name: str,
    aliases: list[str],
    lookback_months: int,
) -> CandidateEvaluation:
    """把模型抽取降级为候选，只有可在原页复核的内容才能成为快照。"""

    errors: list[str] = []
    title = str(extracted.get("title", "")).strip()[:256]
    company = str(extracted.get("company", "")).strip()[:256]
    region = str(extracted.get("region", "")).strip()[:128]
    if not _host_allowed(state.url, tuple(source["domains"])):
        errors.append("来源网址不在官方白名单")
    network_evidence = " ".join(state.network_json)
    original_evidence = f"{state.text} {network_evidence}"
    if not title:
        errors.append("岗位名称为空")
    elif not _contains_untrusted_value(title, original_evidence):
        errors.append("岗位名称无法在原页面中复核")
    evidence = _clean_text(f"{title} {_job_relevant_text(original_evidence)}")
    if not any(marker in evidence for marker in _JOB_INDICATORS):
        errors.append("页面缺少岗位职责或任职要求等招聘语义")
    score = _match_score(position_name, aliases, evidence, headline=title)
    if score < 0.25:
        errors.append(f"与目标岗位相关度不足（{score:.2f}）")
    if company and not _contains_untrusted_value(company, original_evidence):
        company = ""
    if region and not _contains_untrusted_value(region, original_evidence):
        region = ""
    publication = extract_publication_date(state.html, state.text)
    url_hash = hashlib.sha256(state.url.encode()).hexdigest()
    snapshot = None
    if not errors:
        snapshot = {
            "title": title,
            "company": company or str(source["name"]),
            "region": region,
            "source_name": str(source["name"]),
            "source_url": state.url,
            "source_url_hash": url_hash,
            "snippet": _clean_text(state.text)[:500],
            "content": _clean_text(original_evidence)[:12_000],
            "content_hash": hashlib.sha256(evidence.encode()).hexdigest(),
            "published_at": publication.value,
            "published_at_raw": publication.raw,
            "published_at_source": publication.source,
            "date_confidence": publication.confidence,
            "date_parse_reason": publication.reason,
            "skills": _extract_skills(evidence),
            "match_score": score,
            "metadata_json": {
                "discovery_method": "constrained_llm_browser",
                "source_tier": "official_enterprise",
                "search_mode": "history_backfill" if lookback_months else "latest",
                "lookback_months": lookback_months,
                "published_at_source": publication.source,
                "date_confidence": publication.confidence,
                "teacher_reviewed": False,
                "llm_fields_verified_against_page": True,
            },
        }
    confidence = max(0.0, min(1.0, score if not errors else score * 0.5))
    return CandidateEvaluation(
        source_name=str(source["name"]),
        source_url=state.url,
        extracted={"title": title, "company": company, "region": region},
        raw_content=_clean_text(original_evidence)[:12_000],
        status="accepted" if snapshot else "rejected",
        errors=errors,
        confidence=confidence,
        snapshot=snapshot,
    )


ProgressCallback = Callable[[str, int, dict[str, int]], Awaitable[None]]
CancelCallback = Callable[[], Awaitable[bool]]


class PositionBrowserAgent:
    """在两个官方招聘站上执行有预算、可审计的 LLM 浏览循环。"""

    def __init__(self, *, browser_factory: Callable[[], BrowserSession] | None = None, gateway: Any = None) -> None:
        self.settings = get_settings()
        self.browser_factory = browser_factory or PlaywrightBrowserSession
        self.gateway = gateway or get_gateway()

    async def _action(self, state: BrowserPageState, context: dict[str, Any]) -> dict[str, Any]:
        controls = json.dumps(state.controls, ensure_ascii=False)[:8_000]
        network = "\n".join(state.network_json)[:6_000]
        system_prompt, user_prompt = await get_prompt_messages(
            "position_browser_action",
            {
                "position_name": context["position_name"],
                "aliases": json.dumps(context.get("aliases", []), ensure_ascii=False),
                "page_url": state.url,
                "page_title": state.title,
                "page_text": state.text[:12_000],
                "controls": controls,
                "network_json": network,
            },
        )
        result = await self.gateway.chat_structured(
            [
                LLMMessage.system(system_prompt),
                LLMMessage.user(user_prompt),
            ],
            schema_description=(
                '{"action":"click|fill|navigate|back|extract|finish|blocked",'
                '"ref":"控件编号", "url":"官方白名单网址", "reason":"原因"}'
            ),
            temperature=0.0,
            max_tokens=500,
            timeout=30,
        )
        if not result.success or not result.data:
            raise RuntimeError(f"LLM 页面决策失败：{result.error or '无结构化结果'}")
        return result.data

    async def _extract(self, state: BrowserPageState, position_name: str) -> list[dict[str, Any]]:
        system_prompt, user_prompt = await get_prompt_messages(
            "position_browser_extract",
            {
                "position_name": position_name,
                "page_url": state.url,
                "page_title": state.title,
                "page_text": state.text[:15_000],
                "network_json": " ".join(state.network_json)[:6_000],
            },
        )
        result = await self.gateway.chat_structured(
            [
                LLMMessage.system(system_prompt),
                LLMMessage.user(user_prompt),
            ],
            schema_description=(
                '{"items":[{"title":"页面原文岗位名","company":"页面原文公司名或空",'
                '"region":"页面原文地区或空"}]}'
            ),
            temperature=0.0,
            max_tokens=1800,
            timeout=40,
        )
        if not result.success or not result.data:
            raise RuntimeError(f"LLM 岗位抽取失败：{result.error or '无结构化结果'}")
        items = result.data.get("items", [])
        return [item for item in items if isinstance(item, dict)][:20] if isinstance(items, list) else []

    async def discover(
        self,
        *,
        position_name: str,
        aliases: list[str],
        description: str,
        max_results: int,
        lookback_months: int,
        progress: ProgressCallback | None = None,
        should_cancel: CancelCallback | None = None,
    ) -> BrowserDiscoveryResult:
        del description  # 当前由页面证据和岗位名称/别名进行确定性校验
        max_steps = max(4, min(self.settings.position_browser_max_steps, 60))
        max_pages = max(2, min(self.settings.position_browser_max_pages, 30))
        candidates: list[CandidateEvaluation] = []
        reports: list[dict[str, Any]] = []
        warnings: list[str] = []
        visited: set[str] = set()
        extracted_urls: set[str] = set()
        stats = {"browser_pages": 0, "browser_actions": 0, "candidate_count": 0, "accepted_count": 0, "rejected_count": 0}

        async def report(stage: str, value: int) -> None:
            if progress:
                await progress(stage, value, dict(stats))

        await report("starting_browser", 3)
        try:
            async with self.browser_factory() as browser:
                for source_index, source in enumerate(_SOURCES):
                    if should_cancel and await should_cancel():
                        raise BrowserAgentCancelled("教师已取消任务")
                    source_errors: list[str] = []
                    source_candidates = 0
                    source_visited: set[str] = set()
                    blocked = False
                    maintenance = False
                    entered = False
                    source_deadline = time.monotonic() + self.settings.position_browser_source_timeout_seconds
                    try:
                        state = await browser.goto(str(source["start_url"]), tuple(source["domains"]))
                        entered = True
                        stats["browser_pages"] += 1
                        visited.add(state.url)
                        source_visited.add(state.url)
                        for step in range(max_steps // len(_SOURCES)):
                            if should_cancel and await should_cancel():
                                raise BrowserAgentCancelled("教师已取消任务")
                            lowered = f"{state.title}\n{state.text}".lower()
                            if any(marker in lowered for marker in _BLOCK_MARKERS):
                                source_errors.append("页面出现验证码或访问限制，已按规则停止")
                                blocked = True
                                break
                            if _looks_like_maintenance(state.title, state.text):
                                source_errors.append("官网显示正在维护或升级，已停止该来源")
                                maintenance = True
                                break
                            if time.monotonic() > source_deadline:
                                source_errors.append(
                                    f"单来源执行时间达到 {self.settings.position_browser_source_timeout_seconds} 秒上限，已停止"
                                )
                                break
                            await report(
                                f"browsing_{source['key']}",
                                8 + source_index * 42 + min(36, step * 5),
                            )
                            action = await self._action(
                                state,
                                {"position_name": position_name, "aliases": aliases},
                            )
                            stats["browser_actions"] += 1
                            action_name = str(action.get("action", "finish")).lower()
                            if action_name == "extract":
                                if state.url in extracted_urls:
                                    source_errors.append("同一页面重复抽取，已停止该页面循环")
                                    break
                                extracted_urls.add(state.url)
                                for item in await self._extract(state, position_name):
                                    evaluated = validate_browser_candidate(
                                        extracted=item,
                                        state=state,
                                        source=source,
                                        position_name=position_name,
                                        aliases=aliases,
                                        lookback_months=lookback_months,
                                    )
                                    candidates.append(evaluated)
                                    source_candidates += 1
                                # 抽取后交由模型基于新快照决定翻页或返回。
                                action_name = "back" if len(source_visited) > 1 else "finish"
                            if action_name == "click":
                                state = await browser.click(str(action.get("ref", "")), tuple(source["domains"]))
                            elif action_name == "fill":
                                state = await browser.fill(
                                    str(action.get("ref", "")),
                                    position_name,
                                    tuple(source["domains"]),
                                )
                            elif action_name == "navigate":
                                state = await browser.goto(str(action.get("url", "")), tuple(source["domains"]))
                            elif action_name == "back":
                                state = await browser.back(tuple(source["domains"]))
                            elif action_name in {"finish", "blocked"}:
                                if action_name == "blocked":
                                    source_errors.append(str(action.get("reason", "页面访问受限"))[:300])
                                    blocked = True
                                break
                            else:
                                source_errors.append(f"LLM 返回不支持的动作：{action_name}")
                                break
                            if state.url not in visited:
                                visited.add(state.url)
                                stats["browser_pages"] += 1
                            source_visited.add(state.url)
                            if len(visited) >= max_pages or len(candidates) >= max_results:
                                break
                        if source_candidates:
                            status = "available"
                        elif blocked:
                            status = "access_restricted"
                        elif maintenance:
                            status = "maintenance"
                        else:
                            status = "empty"
                    except BrowserAgentCancelled:
                        raise
                    except Exception as exc:  # noqa: BLE001
                        logger.warning("官方浏览器采集失败 source={} error={}", source["key"], exc)
                        source_errors.append(f"{type(exc).__name__}: {str(exc)[:300]}")
                        if isinstance(exc, BrowserAgentUnavailable) or entered:
                            status = "unavailable"
                        else:
                            status = "network_error"
                    reports.append(
                        {
                            "source": source["name"],
                            "status": status,
                            "available": status in {"available", "empty"},
                            "url": source["start_url"],
                            "detail": f"浏览{stats['browser_pages']}页，抽取{source_candidates}个候选" + (f"；{'；'.join(source_errors)}" if source_errors else ""),
                        }
                    )
                    warnings.extend(f"{source['name']}：{item}" for item in source_errors)
                    if len(candidates) >= max_results:
                        break
        except BrowserAgentUnavailable:
            raise

        deduped: dict[str, dict[str, Any]] = {}
        for candidate in candidates:
            if candidate.snapshot:
                deduped.setdefault(candidate.snapshot["source_url_hash"], candidate.snapshot)
        hits = sorted(deduped.values(), key=lambda item: item["match_score"], reverse=True)[:max_results]
        stats["candidate_count"] = len(candidates)
        stats["accepted_count"] = sum(item.status == "accepted" for item in candidates)
        stats["rejected_count"] = sum(item.status == "rejected" for item in candidates)
        await report("completed", 100)
        diagnostic = (
            f"AI 浏览器访问官方页面{stats['browser_pages']}页，执行{stats['browser_actions']}个受约束动作，"
            f"抽取{len(candidates)}个候选，经原页和岗位相关性校验后保留{len(hits)}条。"
        )
        return BrowserDiscoveryResult(
            hits=hits,
            candidates=candidates,
            source_reports=reports,
            warnings=warnings,
            stage_stats=stats,
            diagnostic=diagnostic,
        )


__all__ = [
    "BrowserAgentCancelled",
    "BrowserAgentUnavailable",
    "BrowserDiscoveryResult",
    "BrowserPageState",
    "CandidateEvaluation",
    "PositionBrowserAgent",
    "PlaywrightBrowserSession",
    "RESTRICTED_SOURCE_STATUSES",
    "final_run_status",
    "filter_duplicate_snapshots",
    "validate_browser_candidate",
    "_assert_allowed",
    "_host_allowed",
    "_is_attachment_url",
    "_looks_like_maintenance",
]
