"""从公开白名单来源发现与专业岗位相关的招聘信息。"""

from __future__ import annotations

import asyncio
import hashlib
import html
import json
import re
import ssl
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from html.parser import HTMLParser
from typing import Any
from urllib.parse import urljoin, urlparse

import httpx

from app.core.config import get_settings
from app.core.logging import logger
from app.llm import get_gateway
from app.llm.base import LLMMessage
from app.services.prompt_templates import get_prompt_messages


@dataclass(slots=True)
class SearchHit:
    title: str
    url: str
    snippet: str
    source_name: str
    published_at: datetime | None = None


@dataclass(slots=True)
class PublicationDateEvidence:
    value: datetime | None
    raw: str
    source: str
    confidence: str
    reason: str


@dataclass(slots=True)
class FetchedPage:
    text: str
    publication: PublicationDateEvidence


@dataclass(slots=True)
class OfficialPosting:
    title: str
    company: str
    region: str
    source_name: str
    url: str
    snippet: str
    content: str
    published_at: datetime
    published_at_raw: str
    published_at_source: str
    date_parse_reason: str
    metadata: dict[str, Any]


@dataclass(slots=True)
class DiscoveryResult:
    query_terms: list[str]
    source_domains: list[str]
    hits: list[dict[str, Any]]
    errors: list[str]
    stage_stats: dict[str, int]
    official_sources: list[dict[str, Any]]
    diagnostic: str


def _month_search_windows(
    lookback_months: int,
    *,
    now: datetime | None = None,
) -> list[tuple[datetime, datetime]]:
    """生成包含当前月在内的自然月窗口，供真实历史招聘页回补检索使用。"""
    current = now or datetime.now(UTC)
    absolute_now = current.year * 12 + current.month - 1
    windows: list[tuple[datetime, datetime]] = []
    for offset in range(max(0, lookback_months) - 1, -1, -1):
        absolute = absolute_now - offset
        start = datetime(absolute // 12, absolute % 12 + 1, 1, tzinfo=UTC)
        next_absolute = absolute + 1
        end = datetime(next_absolute // 12, next_absolute % 12 + 1, 1, tzinfo=UTC)
        windows.append((start, end))
    return windows


_SOURCE_DOMAINS: tuple[tuple[str, str], ...] = (
    ("ncss.cn", "国家大学生就业服务平台"),
    ("job.mohrss.gov.cn", "中国公共招聘网"),
    ("zhaopin.cnpc.com.cn", "中国石油高校毕业生招聘平台"),
    ("job.sinopec.com", "中国石化人才招聘网"),
    ("cnpc.com.cn", "中国石油官方招聘"),
    ("sinopec.com", "中国石化官方招聘"),
    ("pipechina.com.cn", "国家管网官方招聘"),
    ("zhaopin.pipechina.com.cn", "国家管网招聘平台"),
    ("pipechina.hotjob.cn", "国家管网招聘平台"),
    ("career.cnooc.com.cn", "中国海油招聘平台"),
    ("oiljob.cn", "石油人才招聘公开页面"),
    ("edu.cn", "高校就业网站"),
)

_OFFICIAL_ENTERPRISE_DOMAINS = {
    "zhaopin.cnpc.com.cn",
    "cnpc.com.cn",
    "job.sinopec.com",
    "sinopec.com",
    "pipechina.com.cn",
    "zhaopin.pipechina.com.cn",
    "pipechina.hotjob.cn",
}

_SINOPEC_SOCIAL_API = (
    "https://job.sinopec.com/api/sz/socialJobInfo/selectSocialJobVoByPage"
)
_SINOPEC_CAMPUS_API = (
    "https://job.sinopec.com/api/upgrade/homepage/selectPositionList"
)
_CNPC_RECRUIT_URL = "https://zhaopin.cnpc.com.cn/"
_PIPECHINA_RECRUIT_URL = "https://zhaopin.pipechina.com.cn/recruit"

_OFFICIAL_REQUEST_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 Chrome/124.0 Safari/537.36 OilTrainSafe/1.0"
    )
}


def _is_certificate_verification_error(exc: BaseException) -> bool:
    """判断异常链中是否包含 TLS 证书校验失败。

    httpx 会把 ssl.SSLCertVerificationError 包装成 ConnectError，
    必须沿 __cause__/__context__ 链定位真实原因，否则日志只剩
    “ConnectError”，无法与断网、DNS 故障区分。
    """

    current: BaseException | None = exc
    seen: set[int] = set()
    while current is not None and id(current) not in seen:
        seen.add(id(current))
        if isinstance(current, ssl.SSLCertVerificationError):
            return True
        current = current.__cause__ or current.__context__
    return False

_OFFICIAL_SEARCH_KEYWORDS = (
    "油气储运", "长输", "管道", "站场", "场站", "集输", "输油", "输气",
    "计量", "检验", "仪表", "储罐", "调压", "燃气", "输配", "运维",
)

# 搜索引擎结果具有波动性；保留可公开访问的行业招聘列表入口作为候选补充。
# 入口本身仍须通过白名单校验，展开后的详情仍须通过招聘语义和岗位相关性过滤。
_DIRECT_RECRUITMENT_ENTRIES: tuple[SearchHit, ...] = (
    SearchHit(
        title="石油人才招聘公开职位列表",
        url="https://www.oiljob.cn/jobseeker/stage/findjob.html",
        snippet="石油石化行业公开招聘职位列表",
        source_name="石油人才招聘公开页面",
    ),
)

_SKILL_TERMS = (
    "油气储运",
    "输油",
    "输气",
    "集输",
    "管道",
    "站场",
    "储罐",
    "机泵",
    "压缩机",
    "阀门",
    "仪表",
    "计量",
    "调压",
    "巡检",
    "设备运维",
    "工艺流程",
    "参数监控",
    "异常识别",
    "风险辨识",
    "HSE",
    "安全管理",
    "应急管理",
    "数据分析",
    "规范记录",
)

_JOB_INDICATORS = (
    "招聘",
    "职位",
    "岗位职责",
    "任职要求",
    "应聘",
    "校园招聘",
    "社会招聘",
    "招聘公告",
    "招聘岗位",
)

_POSITION_ANCHOR_TERMS = (
    "油气储运", "长输", "管道", "站场", "场站", "集输", "输油", "输气", "输送",
    "运行", "操作", "巡检", "值班", "运维", "计量", "检验", "仪表", "设备",
    "储罐", "调度", "安全", "HSE", "应急", "维修", "检测",
)

_DATE_PATTERNS = (
    re.compile(r"(?P<y>20\d{2})[-/.年](?P<m>\d{1,2})[-/.月](?P<d>\d{1,2})日?"),
    re.compile(r"(?P<y>20\d{2})(?P<m>\d{2})(?P<d>\d{2})"),
)


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._skip_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        del attrs
        if tag.lower() in {"script", "style", "noscript", "svg"}:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in {"script", "style", "noscript", "svg"} and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if not self._skip_depth:
            text = re.sub(r"\s+", " ", data).strip()
            if text:
                self.parts.append(text)


def _source_for_url(url: str) -> tuple[str, str] | None:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return None
    host = parsed.hostname.lower().rstrip(".")
    for domain, name in _SOURCE_DOMAINS:
        if host == domain or host.endswith(f".{domain}"):
            return domain, name
    return None


def _clean_text(value: str, limit: int = 12_000) -> str:
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    value = re.sub(r"[\x00-\x08\x0b\x0c\x0e-\x1f]", " ", value)
    value = re.sub(r"\s+", " ", value).strip()
    return value[:limit]


def _extract_page_text(content: str) -> str:
    parser = _VisibleTextParser()
    parser.feed(content)
    return _clean_text(" ".join(parser.parts))


def _extract_date(*texts: str) -> datetime | None:
    blob = " ".join(texts)
    for pattern in _DATE_PATTERNS:
        match = pattern.search(blob)
        if not match:
            continue
        try:
            return datetime(
                int(match.group("y")),
                int(match.group("m")),
                int(match.group("d")),
                tzinfo=UTC,
            )
        except ValueError:
            continue
    return None


def _parse_official_datetime(value: Any) -> datetime | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    for pattern in ("%Y.%m.%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, pattern).replace(tzinfo=UTC)
        except ValueError:
            continue
    return _validated_date(raw)


def _official_keywords(position_name: str, aliases: list[str]) -> list[str]:
    combined = " ".join([position_name, *aliases])
    specific = [term for term in _OFFICIAL_SEARCH_KEYWORDS if term in combined]
    fallback = position_name.removesuffix("岗位").strip()
    return list(dict.fromkeys([*specific, fallback]))[:3]


def _parse_sinopec_social_payload(
    payload: dict[str, Any],
    *,
    end_tag: str,
) -> list[OfficialPosting]:
    """解析中国石化公开社会招聘接口；timeStart 是官网展示的招聘开始时间。"""
    data = payload.get("data") if isinstance(payload, dict) else None
    records = data.get("records", []) if isinstance(data, dict) else []
    if not isinstance(records, list):
        return []
    postings: list[OfficialPosting] = []
    for raw_item in records:
        if not isinstance(raw_item, dict):
            continue
        published_raw = str(raw_item.get("timeStart") or "").strip()
        published_at = _parse_official_datetime(published_raw)
        item_id = str(raw_item.get("id") or "").strip()
        duties = _clean_text(str(raw_item.get("duties") or ""), 256)
        campaign = _clean_text(str(raw_item.get("jobName") or ""), 256)
        if not item_id or not duties or published_at is None:
            continue
        company = _clean_text(str(raw_item.get("department") or "中国石化"), 256)
        region = _clean_text(str(raw_item.get("workLocation") or ""), 128)
        conditions = _clean_text(str(raw_item.get("positionCondition") or ""), 5000)
        treatment = _clean_text(str(raw_item.get("postTreatment") or ""), 1000)
        number = raw_item.get("number")
        url = (
            "https://job.sinopec.com/#/social/jobDetail"
            f"?id={item_id}&endTag={end_tag}"
        )
        content = _clean_text(
            f"中国石化官方社会招聘。招聘项目：{campaign}。"
            f"招聘岗位：{duties}。岗位职责：{duties}。"
            f"任职要求：{conditions}。工作地点：{region}。"
            f"招聘人数：{number if number is not None else '未注明'}。"
            f"岗位待遇：{treatment}。招聘开始时间：{published_raw}。",
            12_000,
        )
        postings.append(
            OfficialPosting(
                title=duties,
                company=company,
                region=region,
                source_name="中国石化人才招聘网",
                url=url,
                snippet=_clean_text(f"{campaign}；{conditions}", 1000),
                content=content,
                published_at=published_at,
                published_at_raw=published_raw,
                published_at_source="official_api_timeStart",
                date_parse_reason="中国石化公开招聘接口 timeStart（招聘开始时间）",
                metadata={
                    "official_record_id": item_id,
                    "official_campaign_id": str(raw_item.get("jobId") or ""),
                    "end_tag": end_tag,
                    "recruitment_number": number,
                    "recruitment_end_at": str(raw_item.get("timeEnd") or ""),
                },
            )
        )
    return postings


def _official_web_status(
    source: str,
    url: str,
    *,
    status_code: int | None,
    content: str = "",
    error: str = "",
) -> dict[str, Any]:
    """把官网入口响应归一为教师可理解、可审计的来源状态。"""
    if status_code == 412:
        return {
            "source": source,
            "status": "access_restricted",
            "available": False,
            "url": url,
            "detail": "招聘平台返回 HTTP 412，当前服务器环境无法直接读取岗位；未绕过官网访问限制",
        }
    if status_code is not None and status_code >= 400:
        return {
            "source": source,
            "status": "unavailable",
            "available": False,
            "url": url,
            "detail": f"招聘入口返回 HTTP {status_code}",
        }
    normalized = _clean_text(content, 6000)
    if "系统维护中" in normalized:
        period = re.search(r"维护时间[:：]?\s*([^。]+)", normalized)
        suffix = f"（{period.group(1).strip()}）" if period else ""
        return {
            "source": source,
            "status": "maintenance",
            "available": False,
            "url": url,
            "detail": f"招聘平台正在系统维护{suffix}",
        }
    if status_code is not None and 200 <= status_code < 400:
        return {
            "source": source,
            "status": "available",
            "available": True,
            "url": url,
            "detail": "招聘入口可访问，继续通过白名单检索岗位详情",
        }
    return {
        "source": source,
        "status": "unreachable",
        "available": False,
        "url": url,
        "detail": f"本次连接失败（{error or '网络响应异常'}），可稍后重试",
    }


def _validated_date(value: Any) -> datetime | None:
    """解析候选值并拒绝明显不可能的招聘发布日期。"""
    if isinstance(value, datetime):
        parsed = value
        raw = value.isoformat()
    else:
        raw = str(value or "").strip()
        if not raw:
            return None
        try:
            parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            parsed = _extract_date(raw)
            if parsed is None:
                return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    else:
        parsed = parsed.astimezone(UTC)
    now = datetime.now(UTC)
    if parsed.year < 2000 or parsed > now + timedelta(days=1):
        return None
    return parsed


def _json_ld_publication(raw_html: str) -> PublicationDateEvidence | None:
    scripts = re.findall(
        r'<script\b[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>',
        raw_html,
        flags=re.IGNORECASE | re.DOTALL,
    )

    def walk(value: Any) -> PublicationDateEvidence | None:
        if isinstance(value, list):
            for item in value:
                evidence = walk(item)
                if evidence:
                    return evidence
            return None
        if not isinstance(value, dict):
            return None
        raw_type = value.get("@type", "")
        types = raw_type if isinstance(raw_type, list) else [raw_type]
        if any(str(item).lower() == "jobposting" for item in types):
            raw_date = value.get("datePosted")
            parsed = _validated_date(raw_date)
            if parsed:
                return PublicationDateEvidence(
                    parsed,
                    str(raw_date),
                    "json_ld_datePosted",
                    "high",
                    "招聘页结构化数据 JobPosting.datePosted",
                )
        for child in value.values():
            evidence = walk(child)
            if evidence:
                return evidence
        return None

    for script in scripts:
        try:
            payload = json.loads(html.unescape(script).strip())
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        evidence = walk(payload)
        if evidence:
            return evidence
    return None


def _tag_attributes(tag: str) -> dict[str, str]:
    return {
        name.lower(): html.unescape(value).strip()
        for name, _, value in re.findall(
            r"([:\w-]+)\s*=\s*([\"'])(.*?)\2",
            tag,
            flags=re.IGNORECASE | re.DOTALL,
        )
    }


def _meta_publication(raw_html: str) -> PublicationDateEvidence | None:
    accepted = {
        "article:published_time",
        "og:published_time",
        "datepublished",
        "publishdate",
        "pubdate",
        "publish_time",
        "dcterms.date.issued",
    }
    for tag in re.findall(r"<meta\b[^>]*>", raw_html, flags=re.IGNORECASE):
        attrs = _tag_attributes(tag)
        key = (attrs.get("property") or attrs.get("name") or attrs.get("itemprop") or "").lower()
        if key not in accepted:
            continue
        raw_date = attrs.get("content", "")
        parsed = _validated_date(raw_date)
        if parsed:
            return PublicationDateEvidence(
                parsed,
                raw_date,
                f"meta:{key}",
                "high",
                f"招聘页元数据 {key}",
            )
    return None


def _labeled_publication(visible_text: str) -> PublicationDateEvidence | None:
    pattern = re.compile(
        r"(?:职位发布日期|岗位发布日期|招聘开始时间|发布时间|发布日期|发布于)\s*[：:]?\s*"
        r"(?P<date>20\d{2}(?:[-/.年]\d{1,2}[-/.月]\d{1,2}日?|\d{4}))",
        flags=re.IGNORECASE,
    )
    match = pattern.search(visible_text)
    if not match:
        return None
    raw_date = match.group("date")
    parsed = _validated_date(raw_date)
    if not parsed:
        return None
    return PublicationDateEvidence(
        parsed,
        raw_date,
        "labeled_page_text",
        "high",
        f"招聘正文明确标注：{match.group(0)[:80]}",
    )


def extract_publication_date(
    raw_html: str = "",
    visible_text: str = "",
    search_published_at: datetime | None = None,
) -> PublicationDateEvidence:
    """只接受能证明“岗位发布时间”的字段，不从页面中的任意日期猜测。"""
    for extractor, value in (
        (_json_ld_publication, raw_html),
        (_meta_publication, raw_html),
        (_labeled_publication, visible_text),
    ):
        evidence = extractor(value)
        if evidence:
            return evidence
    search_date = _validated_date(search_published_at)
    if search_date:
        return PublicationDateEvidence(
            search_date,
            search_published_at.isoformat() if search_published_at else "",
            "search_result",
            "medium",
            "搜索结果摘要日期，未在招聘详情页结构化字段中复核",
        )
    return PublicationDateEvidence(
        None,
        "",
        "",
        "low",
        "页面未提供可核验的 JobPosting.datePosted、发布日期元数据或明确发布时间标签",
    )


def _extract_skills(text: str) -> list[str]:
    lower = text.lower()
    return [term for term in _SKILL_TERMS if term.lower() in lower]


def _job_relevant_text(text: str) -> str:
    """移除企业介绍和推荐职位，避免页面尾部公共导航污染岗位相关性。"""
    value = text
    for marker in ("企业介绍", "给企业提问", "最新热门招聘", "您可能感兴趣的职位"):
        if marker in value:
            value = value.split(marker, 1)[0]
    return _clean_text(value)


def _position_anchor_terms(position_name: str, aliases: list[str]) -> list[str]:
    combined = " ".join([position_name, *aliases]).lower()
    anchors = [term for term in _POSITION_ANCHOR_TERMS if term.lower() in combined]
    if any(term in combined for term in ("管道", "站场", "长输", "输送")):
        anchors.extend(["管道", "站场", "场站", "长输", "集输", "输油", "输气", "储运"])
    if any(term in combined for term in ("运行", "操作", "运维")):
        anchors.extend(["运行", "操作", "巡检", "值班", "运维"])
    return list(dict.fromkeys(anchors))


def _match_score(
    position_name: str,
    aliases: list[str],
    text: str,
    *,
    headline: str = "",
) -> float:
    normalized = text.lower()
    normalized_headline = headline.lower()
    terms = [position_name, *aliases]
    exact_hits = sum(1 for term in terms if term and term.lower() in normalized)
    anchors = _position_anchor_terms(position_name, aliases)
    headline_hits = sum(1 for term in anchors if term.lower() in normalized_headline)
    content_hits = sum(1 for term in anchors if term.lower() in normalized)
    domain_terms = sum(1 for term in _SKILL_TERMS if term.lower() in normalized)
    score = (
        min(exact_hits * 0.35, 0.55)
        + min(headline_hits * 0.22, 0.55)
        + min(content_hits * 0.07, 0.28)
        + min(domain_terms * 0.015, 0.12)
    )
    return round(min(score, 1.0), 3)


def _parse_rss(xml_text: str) -> list[SearchHit]:
    root = ET.fromstring(xml_text)
    hits: list[SearchHit] = []
    for item in root.findall(".//item"):
        title = _clean_text(item.findtext("title") or "", 256)
        url = (item.findtext("link") or "").strip()
        snippet = _clean_text(item.findtext("description") or "", 1000)
        source = _source_for_url(url)
        if not title or not url or source is None:
            continue
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet=snippet,
                source_name=source[1],
                published_at=_extract_date(title, snippet),
            )
        )
    return hits


def _parse_bing_html(html_text: str) -> list[SearchHit]:
    """解析必应普通结果页；仅保留白名单目标链接。"""
    hits: list[SearchHit] = []
    blocks = re.findall(
        r'<li[^>]+class="[^"]*\bb_algo\b[^"]*"[^>]*>(.*?)</li>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    )
    for block in blocks:
        anchor = re.search(
            r'<h2[^>]*>.*?<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>',
            block,
            flags=re.IGNORECASE | re.DOTALL,
        )
        if not anchor:
            continue
        url = html.unescape(anchor.group(1)).strip()
        source = _source_for_url(url)
        if source is None:
            continue
        title = _clean_text(anchor.group(2), 256)
        paragraph = re.search(r"<p[^>]*>(.*?)</p>", block, flags=re.IGNORECASE | re.DOTALL)
        snippet = _clean_text(paragraph.group(1) if paragraph else "", 1000)
        if title:
            hits.append(
                SearchHit(
                    title=title,
                    url=url,
                    snippet=snippet,
                    source_name=source[1],
                    published_at=_extract_date(title, snippet, block[:2000]),
                )
            )
    return hits


def _extract_candidate_links(
    html_text: str,
    *,
    base_url: str,
    source_name: str,
) -> list[SearchHit]:
    """从招聘列表页展开公开职位详情链接。"""
    hits: list[SearchHit] = []
    seen: set[str] = set()
    for href, label in re.findall(
        r'<a[^>]+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
        html_text,
        flags=re.IGNORECASE | re.DOTALL,
    ):
        url = urljoin(base_url, html.unescape(href).strip())
        if url in seen or _source_for_url(url) is None:
            continue
        path = urlparse(url).path.lower()
        if not re.search(r"/(?:jobs?|position|recruit|zhaopin|campus|detail)/", path):
            continue
        if any(term in path for term in ("login", "register", "company")):
            continue
        title = _clean_text(label, 256)
        if len(title) < 2 or title in {"查看详情", "更多详情", "详情"}:
            continue
        seen.add(url)
        hits.append(
            SearchHit(
                title=title,
                url=url,
                snippet="由公开招聘列表页展开的职位详情",
                source_name=source_name,
            )
        )
        if len(hits) >= 30:
            break
    return hits


def _hidden_form_fields(html_text: str) -> dict[str, str]:
    fields: dict[str, str] = {}
    for tag in re.findall(r"<input\b[^>]*>", html_text, flags=re.IGNORECASE):
        field_type = re.search(r'type=["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        if not field_type or field_type.group(1).lower() != "hidden":
            continue
        name = re.search(r'name=["\']([^"\']+)["\']', tag, flags=re.IGNORECASE)
        value = re.search(r'value=["\']([^"\']*)["\']', tag, flags=re.IGNORECASE)
        if name:
            fields[html.unescape(name.group(1))] = html.unescape(value.group(1) if value else "")
    return fields


class PositionDiscoveryService:
    """查询规划、白名单搜索、正文抽取和岗位匹配。"""

    def __init__(self) -> None:
        self.settings = get_settings()

    async def _generate_terms(
        self,
        position_name: str,
        aliases: list[str],
        description: str,
    ) -> list[str]:
        base = [position_name, *aliases]
        try:
            system_prompt, user_prompt = await get_prompt_messages(
                "position_search_terms",
                {
                    "major": "油气储运工程",
                    "position_name": position_name,
                    "aliases": aliases,
                    "description": description,
                },
            )
            result = await get_gateway().chat_structured(
                [
                    LLMMessage.system(system_prompt),
                    LLMMessage.user(user_prompt),
                ],
                schema_description='{"aliases":["岗位别名"]}',
                temperature=0.1,
                max_tokens=500,
                timeout=30,
            )
            if result.success and result.data:
                raw = result.data.get("aliases", [])
                if isinstance(raw, list):
                    base.extend(str(item).strip() for item in raw if str(item).strip())
        except Exception as exc:  # noqa: BLE001
            logger.warning("岗位检索词生成失败，使用教师输入：{}", exc)
        return list(dict.fromkeys(term[:64] for term in base if term))[:6]

    async def _post_official_api(
        self,
        client: httpx.AsyncClient,
        url: str,
        *,
        json_payload: dict[str, Any],
    ) -> httpx.Response:
        """请求内置白名单的央企官方接口。

        部分央企招聘站（如 job.sinopec.com）未下发完整 TLS 证书链，
        容器内标准 CA 证书包无法构建信任路径，httpx 直接抛
        CERTIFICATE_VERIFY_FAILED。此处仅对固定写死的官方 API 域名
        做一次“跳过校验”的降级重试：URL 不是用户输入，抓取结果仍须
        通过招聘语义、岗位相关性和教师审核三道过滤，降级动作记录告警日志。
        """

        try:
            response = await client.post(url, json=json_payload)
            response.raise_for_status()
            return response
        except Exception as exc:  # noqa: BLE001
            if not _is_certificate_verification_error(exc):
                raise
        logger.warning(
            "官方接口 {} 证书链校验失败，改用跳过校验的独立连接重试（仅限内置白名单域名）",
            url,
        )
        async with httpx.AsyncClient(
            timeout=client.timeout,
            verify=False,
            follow_redirects=True,
            headers=_OFFICIAL_REQUEST_HEADERS,
        ) as fallback_client:
            response = await fallback_client.post(url, json=json_payload)
            response.raise_for_status()
            return response

    async def _search_one(self, client: httpx.AsyncClient, query: str) -> list[SearchHit]:
        rss_response = await client.get(
            self.settings.job_search_url,
            params={"q": query, "format": "rss", "count": "10", "setlang": "zh-hans"},
        )
        rss_response.raise_for_status()
        rss_hits = _parse_rss(rss_response.text)
        html_response = await client.get(
            self.settings.job_search_url,
            params={"q": query, "count": "20", "setlang": "zh-hans"},
        )
        html_response.raise_for_status()
        html_hits = _parse_bing_html(html_response.text)
        deduped: dict[str, SearchHit] = {}
        for hit in [*rss_hits, *html_hits]:
            deduped.setdefault(hit.url, hit)
        return list(deduped.values())

    async def _search_sinopec_official(
        self,
        client: httpx.AsyncClient,
        *,
        keywords: list[str],
        lookback_months: int,
    ) -> tuple[list[OfficialPosting], list[str], int, int, int]:
        """从中国石化无需登录的公开社会招聘接口读取结构化岗位。"""
        end_tags = ["N", *(["Y"] if lookback_months else [])]
        postings: dict[str, OfficialPosting] = {}
        errors: list[str] = []
        request_count = 0
        successful_requests = 0
        raw_posting_urls: set[str] = set()
        windows = _month_search_windows(lookback_months)
        oldest_allowed = windows[0][0] if windows else None
        for end_tag in end_tags:
            for keyword in keywords[:3]:
                request_count += 1
                try:
                    response = await self._post_official_api(
                        client,
                        _SINOPEC_SOCIAL_API,
                        json_payload={
                            "departmentIdEq": None,
                            "searchLike": keyword,
                            "endTag": end_tag,
                            "page": 1,
                            "limit": 30,
                        },
                    )
                    payload = response.json()
                    if not payload.get("success"):
                        errors.append(
                            f"中国石化官方接口({keyword}/{end_tag})："
                            f"{str(payload.get('message') or '返回失败')[:80]}"
                        )
                        continue
                    successful_requests += 1
                    for posting in _parse_sinopec_social_payload(payload, end_tag=end_tag):
                        raw_posting_urls.add(posting.url)
                        if (
                            lookback_months
                            and end_tag == "Y"
                            and oldest_allowed
                            and posting.published_at < oldest_allowed
                        ):
                            continue
                        postings.setdefault(posting.url, posting)
                except Exception as exc:  # noqa: BLE001
                    # 记录完整异常摘要（含 TLS/DNS 等真实原因），而非只有异常类名。
                    errors.append(
                        f"中国石化官方接口({keyword}/{end_tag})："
                        f"{type(exc).__name__}: {str(exc)[:120]}"
                    )
                    # 官网出现访问限制时停止该状态的后续关键词请求，避免重复触发限制。
                    break
        return (
            list(postings.values()),
            errors,
            request_count,
            successful_requests,
            len(raw_posting_urls),
        )

    async def _probe_web_source(
        self,
        client: httpx.AsyncClient,
        *,
        source: str,
        url: str,
        max_attempts: int = 1,
    ) -> dict[str, Any]:
        attempts = max(1, min(max_attempts, 6))
        last_error = ""
        for attempt in range(1, attempts + 1):
            try:
                response = await client.get(url, timeout=5.0)
                if response.status_code >= 500 and attempt < attempts:
                    last_error = f"HTTP {response.status_code}"
                    continue
                status = _official_web_status(
                    source,
                    url,
                    status_code=response.status_code,
                    content=response.text,
                )
                status["request_count"] = attempt
                return status
            except Exception as exc:  # noqa: BLE001
                last_error = type(exc).__name__
        status = _official_web_status(
            source,
            url,
            status_code=None,
            error=last_error,
        )
        status["request_count"] = attempts
        return status

    async def _probe_sinopec_campus(
        self,
        client: httpx.AsyncClient,
        *,
        keyword: str,
    ) -> dict[str, Any]:
        url = "https://job.sinopec.com/#/school/recruitmentPositions"
        try:
            response = await self._post_official_api(
                client,
                _SINOPEC_CAMPUS_API,
                json_payload={"page": 1, "limit": 1, "keyword": keyword},
            )
            payload = response.json()
            message = _clean_text(str(payload.get("message") or ""), 200)
            if payload.get("success"):
                return {
                    "status": "available",
                    "available": True,
                    "url": url,
                    "detail": "校园招聘岗位接口可用",
                }
            if "截止时间" in message or "已过应聘" in message:
                return {
                    "status": "closed",
                    "available": False,
                    "url": url,
                    "detail": f"校园招聘岗位接口已按官网规则关闭（{message}）",
                }
            return {
                "status": "unavailable",
                "available": False,
                "url": url,
                "detail": f"校园招聘岗位接口暂不可用（{message or '官网返回失败'}）",
            }
        except Exception as exc:  # noqa: BLE001
            return {
                "status": "unreachable",
                "available": False,
                "url": url,
                "detail": (
                    f"校园招聘岗位接口本次连接失败"
                    f"（{type(exc).__name__}: {str(exc)[:80]}）"
                ),
            }

    async def _fetch_content(self, client: httpx.AsyncClient, hit: SearchHit) -> FetchedPage | None:
        if _source_for_url(hit.url) is None:
            return None
        official_host = (urlparse(hit.url).hostname or "") in _OFFICIAL_ENTERPRISE_DOMAINS
        try:
            try:
                response = await client.get(hit.url)
            except Exception as exc:  # noqa: BLE001
                # 央企官方详情页与接口共用同一证书链，按同样的白名单降级重试。
                if not (official_host and _is_certificate_verification_error(exc)):
                    raise
                logger.warning(
                    "官方页面 {} 证书链校验失败，改用跳过校验的独立连接重试（仅限内置白名单域名）",
                    hit.url,
                )
                async with httpx.AsyncClient(
                    timeout=client.timeout,
                    verify=False,
                    follow_redirects=True,
                    headers=_OFFICIAL_REQUEST_HEADERS,
                ) as fallback_client:
                    response = await fallback_client.get(hit.url)
            response.raise_for_status()
            if _source_for_url(str(response.url)) is None:
                return None
            content_type = response.headers.get("content-type", "").lower()
            if "text/html" not in content_type and "text/plain" not in content_type:
                return None
            visible_text = _extract_page_text(response.text)
            return FetchedPage(
                text=visible_text,
                publication=extract_publication_date(
                    response.text,
                    visible_text,
                    hit.published_at,
                ),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("招聘页面正文抓取失败 url={} error={}", hit.url, exc)
            return None

    async def inspect_publication_dates(
        self,
        hits: list[SearchHit],
    ) -> dict[str, PublicationDateEvidence]:
        """重新访问招聘详情页，仅核验可审计的岗位发布日期。"""
        timeout = httpx.Timeout(float(self.settings.job_search_timeout))
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 Chrome/124.0 Safari/537.36 OilTrainSafe/1.0"
            )
        }
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=headers,
        ) as client:
            results = await asyncio.gather(
                *(self._fetch_content(client, hit) for hit in hits),
                return_exceptions=True,
            )
        output: dict[str, PublicationDateEvidence] = {}
        for hit, result in zip(hits, results, strict=True):
            if isinstance(result, FetchedPage):
                output[hit.url] = result.publication
            else:
                output[hit.url] = PublicationDateEvidence(
                    None,
                    "",
                    "",
                    "low",
                    "重新访问招聘详情页失败，无法核验发布日期",
                )
        return output

    async def _expand_hit(
        self,
        client: httpx.AsyncClient,
        hit: SearchHit,
    ) -> list[SearchHit]:
        if _source_for_url(hit.url) is None:
            return []
        try:
            response = await client.get(hit.url)
            response.raise_for_status()
            if _source_for_url(str(response.url)) is None:
                return []
            if "text/html" not in response.headers.get("content-type", "").lower():
                return []
            return _extract_candidate_links(
                response.text,
                base_url=str(response.url),
                source_name=hit.source_name,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("招聘列表展开失败 url={} error={}", hit.url, exc)
            return []

    async def _search_direct_keyword(
        self,
        client: httpx.AsyncClient,
        entry: SearchHit,
        keyword: str,
    ) -> list[SearchHit]:
        """使用白名单招聘站点自身的公开表单按岗位关键词检索。"""
        response = await client.get(entry.url)
        response.raise_for_status()
        fields = _hidden_form_fields(response.text)
        fields.update(
            {
                "k": keyword,
                "posCode": "",
                "addressCode": "",
                "UC_Search1$imgBtnSearch.x": "18",
                "UC_Search1$imgBtnSearch.y": "12",
            }
        )
        result = await client.post(entry.url, data=fields)
        result.raise_for_status()
        return _extract_candidate_links(
            result.text,
            base_url=str(result.url),
            source_name=entry.source_name,
        )

    async def discover(
        self,
        *,
        position_name: str,
        aliases: list[str],
        description: str,
        max_results: int | None = None,
        lookback_months: int = 0,
    ) -> DiscoveryResult:
        terms = await self._generate_terms(position_name, aliases, description)
        result_limit = max(1, min(max_results or self.settings.job_search_max_results, 50))
        primary_term = terms[0]
        official_keywords = _official_keywords(position_name, terms[1:])
        official_queries = [
            f'site:zhaopin.cnpc.com.cn ({" OR ".join(official_keywords)}) 招聘',
            f'site:cnpc.com.cn ({" OR ".join(official_keywords)}) 招聘 公告',
            f'site:job.sinopec.com ({" OR ".join(official_keywords)}) 招聘',
            f'site:pipechina.com.cn ({" OR ".join(official_keywords)}) 招聘 公告',
            f'site:zhaopin.pipechina.com.cn ({" OR ".join(official_keywords)}) 招聘',
        ]
        base_queries = [
            f'"{primary_term}" 招聘 岗位职责 任职要求',
            f'{position_name} 油气储运 招聘',
            '油气储运 招聘',
            '油气储运 招聘 岗位要求',
            f'site:ncss.cn "{primary_term}" 招聘',
            f'(site:oiljob.cn OR site:edu.cn) "{primary_term}" 招聘',
        ]
        if len(terms) > 1:
            aliases_query = " OR ".join(terms[1:4])
            base_queries.append(f"({aliases_query}) 油气储运 招聘")
            base_queries.extend(f"{term} 招聘 任职要求" for term in terms[1:4])

        history_queries: list[str] = []
        for start, end in _month_search_windows(min(max(lookback_months, 0), 12)):
            history_queries.append(
                f'"{primary_term}" 油气储运 招聘 '
                f'after:{start:%Y-%m-%d} before:{end:%Y-%m-%d} {start.year}年{start.month}月'
            )
        queries = [*history_queries, *base_queries]

        timeout = httpx.Timeout(float(self.settings.job_search_timeout))
        errors: list[str] = []
        async with httpx.AsyncClient(
            timeout=timeout,
            follow_redirects=True,
            headers=_OFFICIAL_REQUEST_HEADERS,
        ) as client:
            (
                sinopec_postings,
                sinopec_errors,
                sinopec_request_count,
                sinopec_successful_requests,
                sinopec_raw_posting_count,
            ) = (
                await self._search_sinopec_official(
                    client,
                    keywords=official_keywords,
                    lookback_months=lookback_months,
                )
            )
            errors.extend(sinopec_errors)
            cnpc_status, pipechina_status, sinopec_campus_status = await asyncio.gather(
                self._probe_web_source(
                    client,
                    source="中国石油",
                    url=_CNPC_RECRUIT_URL,
                    max_attempts=2,
                ),
                self._probe_web_source(
                    client,
                    source="国家管网",
                    url=_PIPECHINA_RECRUIT_URL,
                    max_attempts=6,
                ),
                self._probe_sinopec_campus(
                    client,
                    keyword=official_keywords[0],
                ),
            )
            direct_keywords = list(
                dict.fromkeys(
                    [
                        position_name.removesuffix("岗位"),
                        *terms[1:3],
                        *[
                            term for term in _position_anchor_terms(position_name, terms[1:])
                            if term in position_name
                        ],
                    ]
                )
            )[:4]
            direct_results = await asyncio.gather(
                *(
                    self._search_direct_keyword(client, entry, keyword)
                    for entry in _DIRECT_RECRUITMENT_ENTRIES
                    for keyword in direct_keywords
                ),
                return_exceptions=True,
            )
            search_results = await asyncio.gather(
                *(self._search_one(client, query) for query in queries),
                return_exceptions=True,
            )
            official_search_results = await asyncio.gather(
                *(self._search_one(client, query) for query in official_queries),
                return_exceptions=True,
            )
            deduped: dict[str, SearchHit] = {}
            for query, result in zip(official_queries, official_search_results, strict=True):
                if isinstance(result, Exception):
                    errors.append(f"重点央企检索 {query[:60]}：{type(result).__name__}")
                    continue
                for hit in result:
                    deduped.setdefault(hashlib.sha256(hit.url.encode()).hexdigest(), hit)
                    if len(deduped) >= result_limit:
                        break
            official_search_candidate_count = len(deduped)
            for query, result in zip(queries, search_results, strict=True):
                if isinstance(result, Exception):
                    errors.append(f"{query[:80]}：{type(result).__name__}")
            # 各月份/检索词轮询取样，避免首个大结果集挤占全部历史回补名额。
            valid_results = [result for result in search_results if isinstance(result, list)]
            max_length = max((len(result) for result in valid_results), default=0)
            for index in range(max_length):
                for result in valid_results:
                    if index >= len(result):
                        continue
                    hit = result[index]
                    deduped.setdefault(hashlib.sha256(hit.url.encode()).hexdigest(), hit)
                    if len(deduped) >= result_limit:
                        break
                if len(deduped) >= result_limit:
                    break
            search_candidate_count = len(deduped)
            landing_by_url: dict[str, SearchHit] = {}
            for hit in [*_DIRECT_RECRUITMENT_ENTRIES, *deduped.values()]:
                landing_by_url.setdefault(hit.url, hit)
            landing_hits = list(landing_by_url.values())[:result_limit]
            expanded_results = await asyncio.gather(
                *(self._expand_hit(client, hit) for hit in landing_hits),
                return_exceptions=True,
            )
            expanded: dict[str, SearchHit] = {}
            for result in [*direct_results, *expanded_results]:
                if isinstance(result, Exception):
                    continue
                for hit in result:
                    expanded.setdefault(hit.url, hit)
                    if len(expanded) >= result_limit:
                        break
            official_landing_hits = [
                hit for hit in landing_hits
                if (_source_for_url(hit.url) or ("", ""))[0] in _OFFICIAL_ENTERPRISE_DOMAINS
            ]
            other_landing_hits = [
                hit for hit in landing_hits if hit not in official_landing_hits
            ]
            official_expanded_hits = [
                hit for hit in expanded.values()
                if (_source_for_url(hit.url) or ("", ""))[0] in _OFFICIAL_ENTERPRISE_DOMAINS
            ]
            other_expanded_hits = [
                hit for hit in expanded.values() if hit not in official_expanded_hits
            ]
            # 重点央企官方结果先占配额，行业聚合站只作为补充。
            hits = [
                *official_expanded_hits,
                *official_landing_hits,
                *other_expanded_hits,
                *other_landing_hits,
            ]
            hit_deduped: dict[str, SearchHit] = {}
            for hit in hits:
                hit_deduped.setdefault(hit.url, hit)
            hits = list(hit_deduped.values())[:result_limit]
            contents = await asyncio.gather(
                *(self._fetch_content(client, hit) for hit in hits),
                return_exceptions=True,
            )

        fetched_content_count = sum(
            1 for item in contents if isinstance(item, FetchedPage) and item.text
        )
        recruitment_semantic_count = 0
        relevant_count = 0
        official_relevant_count = 0
        output: list[dict[str, Any]] = []
        for hit, fetched in zip(hits, contents, strict=True):
            page = fetched if isinstance(fetched, FetchedPage) else None
            content = page.text if page else ""
            relevant_content = _job_relevant_text(content)
            evidence_text = _clean_text(f"{hit.title} {hit.snippet} {relevant_content}")
            if not any(indicator in evidence_text for indicator in _JOB_INDICATORS):
                continue
            recruitment_semantic_count += 1
            score = _match_score(
                position_name,
                terms[1:],
                evidence_text,
                headline=f"{hit.title} {hit.snippet}",
            )
            if score < 0.25:
                continue
            relevant_count += 1
            publication = page.publication if page else extract_publication_date(
                search_published_at=hit.published_at
            )
            output.append(
                {
                    "title": hit.title,
                    "company": hit.source_name,
                    "region": "",
                    "source_name": hit.source_name,
                    "source_url": hit.url,
                    "source_url_hash": hashlib.sha256(hit.url.encode()).hexdigest(),
                    "snippet": hit.snippet,
                    "content": content[:12_000],
                    "content_hash": hashlib.sha256(evidence_text.encode()).hexdigest(),
                    "published_at": publication.value,
                    "published_at_raw": publication.raw,
                    "published_at_source": publication.source,
                    "date_confidence": publication.confidence,
                    "date_parse_reason": publication.reason,
                    "skills": _extract_skills(evidence_text),
                    "match_score": score,
                    "metadata_json": {
                        "discovery_method": "public_search_rss",
                        "source_tier": (
                            "official_enterprise"
                            if (_source_for_url(hit.url) or ("", ""))[0]
                            in _OFFICIAL_ENTERPRISE_DOMAINS
                            else "public_recruitment"
                        ),
                        "search_mode": "history_backfill" if lookback_months else "latest",
                        "lookback_months": lookback_months,
                        "published_at_source": publication.source,
                        "date_confidence": publication.confidence,
                        "teacher_reviewed": False,
                    },
                }
            )

        for posting in sinopec_postings:
            evidence_text = _clean_text(
                f"{posting.title} {posting.snippet} {posting.content}"
            )
            score = _match_score(
                position_name,
                terms[1:],
                evidence_text,
                headline=f"{posting.title} {posting.snippet}",
            )
            if score < 0.25:
                continue
            relevant_count += 1
            official_relevant_count += 1
            url_hash = hashlib.sha256(posting.url.encode()).hexdigest()
            output.append(
                {
                    "title": posting.title,
                    "company": posting.company,
                    "region": posting.region,
                    "source_name": posting.source_name,
                    "source_url": posting.url,
                    "source_url_hash": url_hash,
                    "snippet": posting.snippet,
                    "content": posting.content,
                    "content_hash": hashlib.sha256(evidence_text.encode()).hexdigest(),
                    "published_at": posting.published_at,
                    "published_at_raw": posting.published_at_raw,
                    "published_at_source": posting.published_at_source,
                    "date_confidence": "high",
                    "date_parse_reason": posting.date_parse_reason,
                    "skills": _extract_skills(evidence_text),
                    "match_score": score,
                    "metadata_json": {
                        "discovery_method": "official_structured_api",
                        "source_tier": "official_enterprise",
                        "search_mode": "history_backfill" if lookback_months else "latest",
                        "lookback_months": lookback_months,
                        "published_at_source": posting.published_at_source,
                        "date_confidence": "high",
                        "teacher_reviewed": False,
                        **posting.metadata,
                    },
                }
            )

        output_by_url: dict[str, dict[str, Any]] = {}
        for item in output:
            existing = output_by_url.get(item["source_url_hash"])
            item_rank = (
                item["metadata_json"].get("source_tier") == "official_enterprise",
                item["date_confidence"] == "high",
                item["match_score"],
                len(item["content"]),
            )
            existing_rank = (
                existing["metadata_json"].get("source_tier") == "official_enterprise",
                existing["date_confidence"] == "high",
                existing["match_score"],
                len(existing["content"]),
            ) if existing else (False, False, 0.0, 0)
            if existing is None or item_rank > existing_rank:
                output_by_url[item["source_url_hash"]] = item
        output = list(output_by_url.values())
        output.sort(
            key=lambda item: (
                item["metadata_json"].get("source_tier") == "official_enterprise",
                item["date_confidence"] == "high",
                item["match_score"],
                len(item["content"]),
            ),
            reverse=True,
        )
        output = output[:result_limit]
        official_relevant_count = sum(
            1
            for item in output
            if item["metadata_json"].get("source_tier") == "official_enterprise"
        )
        if sinopec_successful_requests:
            range_label = (
                f"近{lookback_months}个月" if lookback_months else "当前范围"
            )
            sinopec_status = {
                "source": "中国石化",
                "status": "available",
                "available": True,
                "url": "https://job.sinopec.com/",
                "detail": (
                    f"社会招聘接口正常：原始命中{sinopec_raw_posting_count}条，"
                    f"{range_label}保留{len(sinopec_postings)}条；"
                    f"{sinopec_campus_status['detail']}"
                ),
            }
        else:
            sinopec_status = {
                "source": "中国石化",
                "status": sinopec_campus_status["status"],
                "available": sinopec_campus_status["available"],
                "url": "https://job.sinopec.com/",
                "detail": (
                    "社会招聘接口本次未成功；"
                    f"{sinopec_campus_status['detail']}"
                ),
            }
        official_sources = [cnpc_status, sinopec_status, pipechina_status]
        stage_stats = {
            "official_search_candidates": official_search_candidate_count,
            "official_structured_positions": len(sinopec_postings),
            "official_structured_raw_positions": sinopec_raw_posting_count,
            "official_source_requests": (
                sinopec_request_count
                + int(cnpc_status.get("request_count", 1))
                + int(pipechina_status.get("request_count", 1))
                + 1
            ),
            "official_relevant_positions": official_relevant_count,
            "search_candidates": search_candidate_count,
            "direct_entries": len(_DIRECT_RECRUITMENT_ENTRIES),
            "direct_search_positions": sum(
                len(result) for result in direct_results if isinstance(result, list)
            ),
            "expanded_positions": len(expanded),
            "fetched_pages": fetched_content_count,
            "recruitment_semantic": recruitment_semantic_count,
            "relevant_positions": relevant_count,
        }
        official_available = any(
            bool(source.get("available")) for source in official_sources
        )
        if output:
            diagnostic = (
                f"重点央企官方候选{official_search_candidate_count}条、结构化岗位"
                f"{len(sinopec_postings)}条，其中相关{official_relevant_count}条；"
                f"全部搜索候选{search_candidate_count}条，展开职位{len(expanded)}条，"
                f"最终保存候选{len(output)}条"
            )
        elif not expanded:
            diagnostic = "搜索结果未包含可展开的招聘详情，招聘站点可能暂时限制访问或页面结构已变化"
        elif recruitment_semantic_count == 0:
            diagnostic = "已取得候选页面，但正文未包含招聘职责、任职要求等可验证语义"
        elif not official_available:
            unreachable = "、".join(
                f"{source['source']}({source['status']})"
                for source in official_sources
                if not source.get("available")
            )
            diagnostic = (
                f"央企官方渠道本次均无法直接访问（{unreachable}），"
                f"已展开{len(expanded)}条公共候选页面但与岗位相关性不足，可稍后重试"
            )
        else:
            diagnostic = "候选招聘页面与当前岗位名称、别名及油气储运技能的相关性不足"
        return DiscoveryResult(
            query_terms=terms,
            source_domains=sorted({urlparse(item["source_url"]).hostname or "" for item in output}),
            hits=output,
            errors=errors,
            stage_stats=stage_stats,
            official_sources=official_sources,
            diagnostic=diagnostic,
        )


__all__ = [
    "DiscoveryResult",
    "OfficialPosting",
    "PublicationDateEvidence",
    "PositionDiscoveryService",
    "SearchHit",
    "extract_publication_date",
    "_month_search_windows",
    "_parse_bing_html",
    "_parse_sinopec_social_payload",
    "_official_web_status",
    "_official_keywords",
    "_extract_candidate_links",
    "_parse_rss",
]
