"""文档解析器（第三十二节）。

支持 PDF（PyMuPDF/fitz）、DOCX（python-docx）、TXT/MD。
解析 → 表格结构化 → 清洗 → 返回纯文本。不连真实设备/不调用外部服务。
未安装解析依赖时优雅降级并明确报错。

表格策略：PDF 用 find_tables 识别并以 Markdown 表格文本输出，
同时从页面文本中剔除表格区域避免重复；DOCX 按文档元素顺序
交替输出段落与表格（paragraphs 不含表格，单独遍历会丢表）。
页眉页脚：跨页频次启发，高频短行视为页眉/页脚剔除。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from app.rag.cleaner import clean_text

_TABLE_MARKER = "【表格】"
# 页眉/页脚判定：短行且出现在超过该比例页面中
_REPEATED_LINE_RATIO = 0.4
_REPEATED_LINE_MAX_LEN = 40


@dataclass
class ParsedDocument:
    """解析结果。"""

    text: str
    source_path: str
    source_type: str  # pdf/docx/txt/md
    page_count: int = 0
    error: str = ""
    pages: list[str] = field(default_factory=list)


def parse_document(path: str | Path) -> ParsedDocument:
    """按扩展名分发解析。"""
    p = Path(path)
    if not p.exists():
        return ParsedDocument(text="", source_path=str(p), source_type="", error="文件不存在")
    ext = p.suffix.lower().lstrip(".")
    if ext == "pdf":
        return _parse_pdf(p)
    if ext == "docx":
        return _parse_docx(p)
    if ext in ("txt", "md", "markdown"):
        return _parse_text(p)
    return ParsedDocument(text="", source_path=str(p), source_type=ext, error=f"不支持的格式: {ext}")


def _render_table(rows: list[list]) -> str:
    """将表格行渲染为 Markdown 表格文本（保留结构，供分块与检索）。"""
    clean_rows: list[list[str]] = []
    for row in rows:
        cells = [("" if cell is None else str(cell)).replace("\n", " ").strip() for cell in row]
        if any(cells):
            clean_rows.append(cells)
    if not clean_rows:
        return ""
    width = max(len(r) for r in clean_rows)
    lines = [_TABLE_MARKER]
    for index, row in enumerate(clean_rows):
        padded = row + [""] * (width - len(row))
        lines.append("| " + " | ".join(padded) + " |")
        if index == 0:
            lines.append("|" + " --- |" * width)
    return "\n".join(lines)


def _rect_overlap_ratio(block: tuple, rect) -> float:
    """文本块与表格区域的重叠面积占块面积比例。"""
    x0, y0, x1, y1 = block[0], block[1], block[2], block[3]
    ix0, iy0 = max(x0, rect.x0), max(y0, rect.y0)
    ix1, iy1 = min(x1, rect.x1), min(y1, rect.y1)
    inter = max(0.0, ix1 - ix0) * max(0.0, iy1 - iy0)
    area = max(1e-6, (x1 - x0) * (y1 - y0))
    return inter / area


def _remove_repeated_lines(pages: list[str]) -> list[str]:
    """跨页频次启发式去除页眉/页脚：同一短行出现在过多页面。"""
    if len(pages) < 3:
        return pages
    counter: Counter[str] = Counter()
    for page in pages:
        seen_in_page: set[str] = set()
        for line in page.splitlines():
            stripped = line.strip()
            if 0 < len(stripped) <= _REPEATED_LINE_MAX_LEN and stripped not in seen_in_page:
                seen_in_page.add(stripped)
                counter[stripped] += 1
    threshold = len(pages) * _REPEATED_LINE_RATIO
    noise = {line for line, count in counter.items() if count >= threshold}
    if not noise:
        return pages
    result: list[str] = []
    for page in pages:
        kept = [line for line in page.splitlines() if line.strip() not in noise]
        result.append("\n".join(kept))
    return result


def _parse_pdf(p: Path) -> ParsedDocument:
    try:
        import fitz  # PyMuPDF
    except Exception as exc:  # noqa: BLE001
        return ParsedDocument(text="", source_path=str(p), source_type="pdf", error=f"PyMuPDF 不可用: {exc}")
    try:
        doc = fitz.open(str(p))
        parts: list[str] = []
        for page in doc:
            # 1. 表格识别：结构化输出并从正文中剔除表格区域，避免重复
            table_texts: list[str] = []
            table_rects: list = []
            try:
                for table in page.find_tables().tables:
                    rendered = _render_table(table.extract())
                    if rendered:
                        table_texts.append(rendered)
                        table_rects.append(fitz.Rect(table.bbox))
            except Exception:  # noqa: BLE001 - find_tables 不可用时降级纯文本
                pass
            text_parts: list[str] = []
            try:
                blocks = page.get_text("blocks")
                for block in blocks:
                    if len(block) < 7 or block[6] != 0:  # 仅文本块
                        continue
                    if any(_rect_overlap_ratio(block, rect) > 0.5 for rect in table_rects):
                        continue
                    text_parts.append(str(block[4]))
            except Exception:  # noqa: BLE001
                text_parts.append(page.get_text("text"))
            page_text = "\n".join(text_parts)
            if table_texts:
                page_text = page_text + "\n" + "\n".join(table_texts)
            parts.append(clean_text(page_text))
        parts = _remove_repeated_lines(parts)
        text = clean_text("\n\n".join(parts))
        return ParsedDocument(
            text=text,
            source_path=str(p),
            source_type="pdf",
            page_count=len(doc),
            pages=parts,
        )
    except Exception as exc:  # noqa: BLE001
        return ParsedDocument(text="", source_path=str(p), source_type="pdf", error=str(exc))


def _parse_docx(p: Path) -> ParsedDocument:
    try:
        import docx  # python-docx
        from docx.oxml.ns import qn
        from docx.table import Table as DocxTable
        from docx.text.paragraph import Paragraph
    except Exception as exc:  # noqa: BLE001
        return ParsedDocument(text="", source_path=str(p), source_type="docx", error=f"python-docx 不可用: {exc}")
    try:
        d = docx.Document(str(p))
        parts: list[str] = []
        # 按文档体元素顺序交替处理段落与表格，保留原始位置关系
        for child in d.element.body.iterchildren():
            if child.tag == qn("w:p"):
                para = Paragraph(child, d)
                value = para.text.strip()
                if not value:
                    continue
                style_name = (getattr(para.style, "name", "") or "").lower()
                if style_name.startswith("heading") or "标题" in style_name:
                    parts.append(f"## {value}")
                else:
                    parts.append(value)
            elif child.tag == qn("w:tbl"):
                table = DocxTable(child, d)
                rows = [[cell.text.strip() for cell in row.cells] for row in table.rows]
                rendered = _render_table(rows)
                if rendered:
                    parts.append(rendered)
        text = clean_text("\n".join(parts))
        return ParsedDocument(
            text=text,
            source_path=str(p),
            source_type="docx",
            page_count=1,
            pages=[text],
        )
    except Exception as exc:  # noqa: BLE001
        return ParsedDocument(text="", source_path=str(p), source_type="docx", error=str(exc))


def _parse_text(p: Path) -> ParsedDocument:
    try:
        raw = p.read_text(encoding="utf-8", errors="replace")
    except Exception as exc:  # noqa: BLE001
        return ParsedDocument(text="", source_path=str(p), source_type="txt", error=str(exc))
    text = clean_text(raw)
    return ParsedDocument(
        text=text,
        source_path=str(p),
        source_type=p.suffix.lower().lstrip("."),
        page_count=1,
        pages=[text],
    )


__all__ = ["ParsedDocument", "parse_document"]
