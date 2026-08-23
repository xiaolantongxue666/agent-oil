"""文本清洗（第三十二节）。

对解析后的原始文本做规整，提升分块与检索质量：
- 统一空白与换行
- 去除页眉页脚特征行（启发式，不删正文）
- 折叠重复标点
- 保留专业编号与章节结构标记
"""

from __future__ import annotations

import re

# 页眉页脚特征：纯页码、短横线分隔条
_PAGE_NUM_RE = re.compile(r"^\s*\d+\s*$")
_DASH_LINE_RE = re.compile(r"^[\-=—_·\s]+$")
_MULTI_SPACE_RE = re.compile(r"[ \t　]+")
_MULTI_NEWLINE_RE = re.compile(r"\n{3,}")
_MARKDOWN_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+")
_MARKDOWN_LIST_RE = re.compile(r"^\s*(?:[-*+]\s+|\d+[.)]\s+)")
_MARKDOWN_TABLE_SEPARATOR_RE = re.compile(r"^\s*\|?(?:\s*:?-{3,}:?\s*\|)+\s*$")
_MARKDOWN_FENCE_RE = re.compile(r"^\s*(```|~~~)")


def clean_text(text: str) -> str:
    """清洗原始文本。保守策略：仅规整，不删专业术语/编号。"""
    if not text:
        return ""
    lines = []
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            lines.append("")
            continue
        # 去除页眉页脚特征行
        if _PAGE_NUM_RE.match(stripped) or _DASH_LINE_RE.match(stripped):
            continue
        lines.append(stripped)
    cleaned = "\n".join(lines)
    # 折叠多余空白
    cleaned = _MULTI_SPACE_RE.sub(" ", cleaned)
    cleaned = _MULTI_NEWLINE_RE.sub("\n\n", cleaned)
    return cleaned.strip()


def clean_markdown(text: str) -> str:
    """仅规范 Markdown 的编码和换行，不破坏其展示语义。"""

    if not text:
        return ""
    normalized = text.lstrip("\ufeff").replace("\r\n", "\n").replace("\r", "\n")
    # 保留前导空白、空行、围栏代码块、列表及表格；仅移除每行末尾的无意义空白。
    return "\n".join(line.rstrip() for line in normalized.split("\n")).strip("\n")


def markdown_to_search_text(text: str) -> str:
    """将保真的 Markdown 转成稳定的检索文本，不修改展示原文。"""

    if not text:
        return ""
    lines: list[str] = []
    in_fence = False
    for raw_line in text.splitlines():
        stripped = raw_line.strip()
        if _MARKDOWN_FENCE_RE.match(stripped):
            in_fence = not in_fence
            continue
        if not stripped:
            lines.append("")
            continue
        if not in_fence and _MARKDOWN_TABLE_SEPARATOR_RE.match(stripped):
            continue
        if not in_fence:
            stripped = _MARKDOWN_HEADING_RE.sub("", stripped)
            stripped = _MARKDOWN_LIST_RE.sub("", stripped)
            if stripped.startswith("|") and stripped.endswith("|"):
                stripped = " ".join(cell.strip() for cell in stripped.strip("|").split("|"))
        lines.append(stripped)
    return clean_text("\n".join(lines))


__all__ = ["clean_markdown", "clean_text", "markdown_to_search_text"]
