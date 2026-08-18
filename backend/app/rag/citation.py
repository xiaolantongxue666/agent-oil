"""引用构建（第三十二节）。

原则：只输出 payload 中实际存在的来源信息；无编号/章节/页码则留空，
绝不编造标准编号或页码。教学模拟资料须标注。
"""

from __future__ import annotations

import re
from typing import Any

_MODEL_CITATION_HEADING_RE = re.compile(
    r"(?im)^\s{0,3}(?:#{1,6}\s+)?(?:\*{1,3}\s*)?"
    r"(?:【\s*专业依据\s*】|专业依据(?:（系统核验）)?\s*[:：]?)"
    r"(?:\s*\*{1,3})?\s*$"
)

_TEACHING_NOTE_RE = re.compile(
    r"\*?教学用途说明：以上资料用于教学模拟与脱敏学习，"
    r"资料原始出处以系统核验信息为准。\*?\s*$"
)


def build_citation(payload: dict[str, Any]) -> dict[str, Any]:
    """从 Qdrant payload 构建引用信息（不编造）。"""
    citation: dict[str, Any] = {
        "knowledge_id": payload.get("knowledge_id", ""),
        "title": payload.get("title", ""),
        "source_type": payload.get("source_type", ""),
        "source_name": payload.get("source_name", ""),
        "source_no": payload.get("source_no", ""),  # 无则空
        "chapter": payload.get("chapter", ""),  # 无则空
        "is_teaching_simulation": True,  # 教学模拟/脱敏资料统一标注
    }
    page = payload.get("page")
    if page is not None:
        citation["page"] = int(page)
    else:
        citation["page"] = None  # 无页码则不展示数字
    chunk_id = payload.get("chunk_id")
    citation["chunk_id"] = int(chunk_id) if chunk_id is not None else None
    return citation


def format_citation_text(citation: dict[str, Any]) -> str:
    """将引用渲染为短文本（用于回答末尾的"专业依据"）。"""
    parts: list[str] = []
    if citation.get("source_name"):
        parts.append(citation["source_name"])
    if citation.get("source_no"):
        parts.append(f"编号 {citation['source_no']}")
    if citation.get("chapter"):
        parts.append(citation["chapter"])
    if citation.get("page") is not None:
        parts.append(f"第 {citation['page']} 页")
    if not parts:
        return ""  # 无任何来源信息则不输出引用
    return "来源：" + "，".join(parts)


def format_citation_section(citations: list[dict[str, Any]]) -> str:
    """根据结构化元数据生成可核验的专业依据，不让模型自行编造出处。"""

    lines: list[str] = []
    for citation in citations:
        source = format_citation_text(citation)
        if not source:
            continue
        index = len(lines) + 1
        title = str(citation.get("title") or citation.get("knowledge_id") or "未命名资料")
        lines.append(f"{index}. {title}；{source}")
    if not lines:
        return ""
    return "**专业依据（系统核验）**\n" + "\n".join(lines)


def normalize_citations(value: Any) -> list[dict[str, Any]]:
    """兼容历史 JSON 数据，只保留可安全读取的引用对象。"""

    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def append_verified_citation_section(answer: str, citations: Any) -> str:
    """移除模型自行生成的依据清单，追加由结构化元数据生成的核验结果。"""

    section = format_citation_section(normalize_citations(citations))
    if not section:
        return answer
    heading = _MODEL_CITATION_HEADING_RE.search(answer)
    clean_answer = answer[:heading.start()].rstrip() if heading else answer.rstrip()
    teaching_note = (
        "*教学用途说明：以上资料用于教学模拟与脱敏学习，"
        "资料原始出处以系统核验信息为准。*"
    )
    return f"{clean_answer}\n\n{section}\n\n{teaching_note}"


def strip_model_citation_section(answer: str) -> str:
    """移除回答正文中的专业依据清单（含尾部教学用途说明），不追加任何内容。

    用途：
    - 新回答：剥离模型自行生成的依据清单，防止编造出处混入正文；
      引用信息由前端「引用来源」卡片单独展示。
    - 存量消息：兼容旧版本写入正文的「专业依据（系统核验）」段落。
    """
    clean_answer, _ = split_before_model_citation_section(answer)
    clean_answer = clean_answer.rstrip()
    clean_answer = _TEACHING_NOTE_RE.sub("", clean_answer).rstrip()
    return clean_answer


def split_before_model_citation_section(answer: str) -> tuple[str, bool]:
    """在模型自造的专业依据标题前切断，供完整回答和流式回答共用。"""

    heading = _MODEL_CITATION_HEADING_RE.search(answer)
    if heading is None:
        return answer, False
    return answer[: heading.start()], True


__all__ = [
    "append_verified_citation_section",
    "strip_model_citation_section",
    "split_before_model_citation_section",
    "build_citation",
    "format_citation_section",
    "format_citation_text",
    "normalize_citations",
]
