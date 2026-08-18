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


__all__ = ["clean_text"]
