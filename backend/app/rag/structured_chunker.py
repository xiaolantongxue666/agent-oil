"""面向标准、教材和规程的章节/条款优先分块。"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass

from app.rag.chunker import chunk_text

_MARKDOWN_HEADING = re.compile(r"^\s{0,3}(#{1,6})\s+(.+?)\s*$")
_CHINESE_HEADING = re.compile(
    r"^\s*(第[一二三四五六七八九十百零〇两\d]+[编章节条款部分]"
    r"(?:\s*[-—:：、.]?\s*[^。；;]{0,90})?)\s*$"
)
_NUMBERED_HEADING = re.compile(
    r"^\s*((?:\d+(?:\.\d+){1,5}|[一二三四五六七八九十]+、|"
    r"[（(][一二三四五六七八九十\d]+[）)])\s*[^。；;]{1,90})\s*$"
)
_TOC_ENTRY = re.compile(r"(?:\.{3,}|…{2,}).*\d+\s*$")
_DOTTED_NUM_HEADING = re.compile(r"^(\d+(?:\.\d+){1,5})\b")
_TABLE_MARKER = "【表格】"
# Markdown 表格分隔行：| --- | :---: | 等
_TABLE_SEPARATOR = re.compile(r"^\s*\|(?:\s*:?-+:?\s*\|)+\s*$")

# 中文标题单位 → 层级
_CN_HEADING_LEVELS = {"篇": 1, "编": 1, "部": 1, "章": 1, "节": 2, "条": 3, "款": 4, "项": 4}


@dataclass(slots=True)
class StructuredTextChunk:
    chunk_index: int
    heading: str
    chapter: str
    content: str
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    checksum: str
    heading_path: str = ""
    chunk_type: str = "text"  # text | table


@dataclass(slots=True)
class _Section:
    heading: str
    content: str
    page_start: int | None
    page_end: int | None
    char_start: int
    char_end: int
    heading_path: str = ""
    chunk_type: str = "text"


def split_structured_text(
    text: str,
    *,
    pages: list[str] | None = None,
    max_chars: int = 1800,
) -> list[StructuredTextChunk]:
    """按 Markdown 标题、章/节/条及编号标题切分，超长章节再做长度兜底。

    增强：
    - 目录行（点线+页码）直接从正文剔除，不再混入分块；
    - 维护标题层级栈，每块携带完整标题路径 heading_path；
    - 连续管道表格行独立成块（chunk_type=table），不与前后正文合并；
    - 仅多页来源（PDF 等）记录页码，MD/TXT 等单页来源不再填充"第1页"。
    """
    if not text.strip():
        return []
    source_pages = [page for page in (pages or []) if page.strip()] or [text]
    multi_page = len(source_pages) > 1

    def page_value(page_no: int) -> int | None:
        return page_no if multi_page else None

    sections: list[_Section] = []
    heading = "文档导言"
    heading_stack: list[tuple[int, str]] = [(1, "文档导言")]
    lines: list[str] = []
    started_with_heading = False
    table_lines: list[str] | None = None
    table_page_start: int | None = None
    table_page_end: int | None = None
    table_char_start = 0
    page_start: int | None = None
    page_end: int | None = None
    char_start = 0
    cursor = 0

    def current_path() -> str:
        return " / ".join(title for _, title in heading_stack)

    def flush() -> None:
        nonlocal lines, started_with_heading
        content = "\n".join(lines).strip()
        body_lines = [entry for entry in lines if entry.strip()]
        # 仅含标题行的空节不产生分块：标题信息已由 heading_path 携带
        if content and not (started_with_heading and len(body_lines) <= 1):
            chunk_type = "table" if _TABLE_MARKER in content else "text"
            sections.append(
                _Section(
                    heading=heading,
                    content=content,
                    page_start=page_start,
                    page_end=page_end,
                    char_start=char_start,
                    char_end=char_start + len(content),
                    heading_path=current_path(),
                    chunk_type=chunk_type,
                )
            )
        lines = []
        started_with_heading = False

    def flush_table() -> None:
        nonlocal table_lines
        if table_lines:
            content = "\n".join(table_lines).strip()
            if content:
                sections.append(
                    _Section(
                        heading=heading,
                        content=content,
                        page_start=table_page_start,
                        page_end=table_page_end,
                        char_start=table_char_start,
                        char_end=table_char_start + len(content),
                        heading_path=current_path(),
                        chunk_type="table",
                    )
                )
        table_lines = None

    for page_no, page_text in enumerate(source_pages, 1):
        for raw_line in page_text.splitlines():
            line = raw_line.strip()
            line_start = cursor
            cursor += len(raw_line) + 1
            if table_lines is not None:
                if line.startswith("|"):
                    # 表内空行不打断表格（GFM 表格宽松延续）
                    table_lines.append(line)
                    table_page_end = page_value(page_no)
                    continue
                if not line:
                    # 暂缓表格结束判定，等待下一行是否仍为表格行
                    continue
                flush_table()
            if not line:
                if lines and lines[-1] != "":
                    lines.append("")
                continue
            if _TOC_ENTRY.search(line):
                # 目录行不入正文，避免污染分块与向量索引
                continue
            if line.startswith("|"):
                # 紧邻的【表格】标记归属表格块，从待落盘文本缓冲中取出
                marker_prefix: list[str] = []
                if lines and lines[-1].strip() == _TABLE_MARKER:
                    marker_prefix = [lines.pop()]
                flush()
                table_lines = [*marker_prefix, line]
                table_page_start = page_value(page_no)
                table_page_end = page_value(page_no)
                table_char_start = line_start
                continue
            detected = _detect_heading(line)
            if detected:
                flush()
                heading, level = detected
                while heading_stack and heading_stack[-1][0] >= level:
                    heading_stack.pop()
                heading_stack.append((level, heading))
                lines = [line]
                started_with_heading = True
                page_start = page_value(page_no)
                page_end = page_value(page_no)
                char_start = line_start
            else:
                if not lines:
                    char_start = line_start
                    page_start = page_value(page_no)
                lines.append(line)
                page_end = page_value(page_no)
    flush_table()
    flush()

    result: list[StructuredTextChunk] = []
    seen_checksums: set[str] = set()
    for section in sections:
        for piece in _split_oversized(section, max_chars=max_chars):
            normalized = re.sub(r"\s+", " ", piece.content).strip()
            if len(normalized) < 8:
                continue
            checksum = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
            if checksum in seen_checksums:
                continue
            seen_checksums.add(checksum)
            result.append(
                StructuredTextChunk(
                    chunk_index=len(result),
                    heading=piece.heading,
                    chapter=piece.heading_path or piece.heading,
                    content=piece.content,
                    page_start=piece.page_start,
                    page_end=piece.page_end,
                    char_start=piece.char_start,
                    char_end=piece.char_end,
                    checksum=checksum,
                    heading_path=piece.heading_path,
                    chunk_type=piece.chunk_type,
                )
            )
    return result


def _detect_heading(line: str) -> tuple[str, int] | None:
    """识别标题行并返回 (标题文本, 层级)；非标题返回 None。"""
    match = _MARKDOWN_HEADING.match(line)
    if match:
        return match.group(2).strip(), min(len(match.group(1)), 6)
    match = _CHINESE_HEADING.match(line)
    if match:
        title = match.group(1).strip()
        level = _CN_HEADING_LEVELS.get(title[1:2], 1) if len(title) > 1 else 1
        return title, level
    match = _NUMBERED_HEADING.match(line)
    if match:
        title = match.group(1).strip()
        dotted = _DOTTED_NUM_HEADING.match(title)
        if dotted:
            # 3.1 → L2，3.1.1 → L3，以点分段数即层级
            level = dotted.group(1).count(".") + 1
        elif title.startswith(("（", "(")):
            level = 3
        else:
            level = 1  # 「一、」类一级编号
        return title, level
    return None


def _split_oversized(section: _Section, *, max_chars: int) -> list[_Section]:
    if len(section.content) <= max_chars:
        return [section]
    if section.chunk_type == "table":
        return _split_table(section, max_chars=max_chars)
    raw_chunks = chunk_text(
        section.content,
        chunk_size=max_chars,
        overlap=min(80, max_chars // 10),
    )
    result: list[_Section] = []
    for index, chunk in enumerate(raw_chunks, 1):
        suffix = f"（续{index}）" if len(raw_chunks) > 1 else ""
        result.append(
            _Section(
                heading=f"{section.heading}{suffix}",
                content=chunk.text,
                page_start=section.page_start,
                page_end=section.page_end,
                char_start=section.char_start + chunk.char_start,
                char_end=section.char_start + chunk.char_end,
                heading_path=section.heading_path,
                chunk_type=section.chunk_type,
            )
        )
    return result


def _split_table(section: _Section, *, max_chars: int) -> list[_Section]:
    """超长表格按数据行分组切分，每片重复表头与分隔行，保留列含义。"""
    content_lines = section.content.splitlines()
    offsets: list[int] = []
    cursor = 0
    for raw in content_lines:
        offsets.append(cursor)
        cursor += len(raw) + 1

    pipe_rows = [
        (index, line)
        for index, line in enumerate(content_lines)
        if line.lstrip().startswith("|")
    ]
    if len(pipe_rows) < 3:
        return [section]

    header_count = 1
    if len(pipe_rows) > 1 and _TABLE_SEPARATOR.match(pipe_rows[1][1]):
        header_count = 2
    header_lines = [line for _, line in pipe_rows[:header_count]]
    data_rows = pipe_rows[header_count:]

    groups: list[list[tuple[int, str]]] = []
    group: list[tuple[int, str]] = []
    group_len = 0
    for index, row in data_rows:
        row_len = len(row) + 1
        if group and group_len + row_len > max_chars:
            groups.append(group)
            group = []
            group_len = 0
        group.append((index, row))
        group_len += row_len
    if group:
        groups.append(group)
    if len(groups) <= 1:
        return [section]

    marker = bool(content_lines) and content_lines[0].strip() == _TABLE_MARKER
    pieces: list[_Section] = []
    for piece_no, rows in enumerate(groups, 1):
        body = header_lines + [line for _, line in rows]
        content = "\n".join(([_TABLE_MARKER] if marker else []) + body)
        first_idx = rows[0][0]
        last_idx = rows[-1][0]
        pieces.append(
            _Section(
                heading=f"{section.heading}（续{piece_no}）",
                content=content,
                page_start=section.page_start,
                page_end=section.page_end,
                char_start=section.char_start + offsets[first_idx],
                char_end=section.char_start + offsets[last_idx] + len(content_lines[last_idx]),
                heading_path=section.heading_path,
                chunk_type="table",
            )
        )
    return pieces


__all__ = ["StructuredTextChunk", "split_structured_text"]
