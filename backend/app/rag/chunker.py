"""文本分块（第三十二节）。

策略：
- 优先按段落/句子边界切分，避免割裂语义
- 滑动窗口重叠（默认 64 字符）
- 目标块大小 512 字符（可配置）
- 每块附加 chunk_index 元数据
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 句子/段落分隔：中文标点后直接切（中文句间无空格），拉丁标点后需空白
_SENT_SPLIT = re.compile(r"(?<=[。！？!?])|(?<=[.!?])\s+")


@dataclass
class Chunk:
    """文本块。"""

    text: str
    chunk_index: int
    char_start: int
    char_end: int

def chunk_text(
    text: str,
    *,
    chunk_size: int = 512,
    overlap: int = 64,
) -> list[Chunk]:
    """将文本切分为带索引的块。

    先按句子/段落切成单元，再贪心拼接到 chunk_size，窗口滑动 overlap。
    """
    if not text:
        return []
    chunk_size = max(1, chunk_size)
    overlap = max(0, min(overlap, chunk_size - 1))

    units = _split_units(text)
    if not units:
        return []

    chunks: list[Chunk] = []
    cur = ""
    cur_start = 0
    idx = 0
    pos = 0
    for unit, start, end in units:
        if not cur:
            cur = unit
            cur_start = start
            pos = end
        elif len(cur) + len(unit) + 1 <= chunk_size:
            cur += "\n" + unit
            pos = end
        else:
            chunks.append(Chunk(cur, idx, cur_start, pos))
            idx += 1
            # 滑动窗口：保留尾部 overlap 字符作为下一块前缀
            tail = cur[-overlap:] if overlap else ""
            cur = (tail + ("\n" + unit if tail else unit)).lstrip()
            cur_start = max(0, pos - overlap)
            pos = end
    if cur:
        chunks.append(Chunk(cur, idx, cur_start, pos))
    return chunks


def _split_units(text: str) -> list[tuple[str, int, int]]:
    """切分为 (单元, 起始, 结束) 列表，保留段落与句子边界。"""
    units: list[tuple[str, int, int]] = []
    cursor = 0
    for para in text.split("\n"):
        if not para.strip():
            cursor += 1
            continue
        # 句子级切分
        last = 0
        for m in _SENT_SPLIT.finditer(para):
            seg = para[last:m.start()].strip()
            if seg:
                units.append((seg, cursor + last, cursor + last + len(seg)))
            last = m.end()
        seg = para[last:].strip()
        if seg:
            units.append((seg, cursor + last, cursor + last + len(seg)))
        cursor += len(para) + 1
    return units


__all__ = ["Chunk", "chunk_text"]
