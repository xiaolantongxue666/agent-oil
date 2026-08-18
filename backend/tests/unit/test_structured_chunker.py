"""章节/条款优先分块测试。"""

from app.rag.structured_chunker import split_structured_text


def test_split_markdown_by_chapter_and_article():
    text = """# 目录
第一章 总则 ........ 1

# 第一章 总则
本章说明油气管道站场的基本要求和工艺流程。

## 第一条 工艺流程
介质依次经过进站、分离、计量、调压和出站功能区。

## 第二条 阀门检查
巡检时应识别球阀、闸阀状态以及泄漏风险。
"""
    chunks = split_structured_text(text)
    headings = [chunk.heading for chunk in chunks]
    # 目录行被剔除后「目录」节无正文，不再生成空块
    assert headings == ["第一章 总则", "第一条 工艺流程", "第二条 阀门检查"]
    assert all(chunk.checksum for chunk in chunks)
    assert [chunk.chunk_index for chunk in chunks] == list(range(len(chunks)))
    # 目录行（点线+页码）不进入任何分块内容
    assert all("........" not in chunk.content for chunk in chunks)
    # 标题层级路径：条款携带所属章的完整路径
    article = next(c for c in chunks if c.heading == "第一条 工艺流程")
    assert article.heading_path == "第一章 总则 / 第一条 工艺流程"
    assert article.chapter == article.heading_path


def test_numbered_heading_levels_build_heading_path():
    text = """第三章 输气站运行
本章介绍输气站运行要求。

3.1 日常巡检
巡检基本要求。

3.1.1 管道定位
依据标志桩识别埋地管道位置。
"""
    chunks = split_structured_text(text)
    located = next(c for c in chunks if "管道定位" in c.heading)
    assert located.heading_path == "第三章 输气站运行 / 3.1 日常巡检 / 3.1.1 管道定位"


def test_table_content_marked_as_table_chunk():
    text = """## 巡检参数表
【表格】
| 参数 | 范围 |
| --- | --- |
| 压力 | 0.2–0.4MPa |
"""
    chunks = split_structured_text(text)
    assert len(chunks) == 1
    assert chunks[0].chunk_type == "table"


def test_long_chapter_uses_length_fallback_without_losing_heading():
    text = "# 第三章 设备检查\n" + "阀门压力仪表检查。" * 300
    chunks = split_structured_text(text, max_chars=300)
    assert len(chunks) > 1
    assert all(chunk.heading.startswith("第三章 设备检查") for chunk in chunks)
    assert all(len(chunk.content) <= 380 for chunk in chunks)


def test_duplicate_sections_are_removed_by_checksum():
    repeated = "## 第一条 阀门检查\n阀门状态与泄漏风险检查。"
    chunks = split_structured_text(f"{repeated}\n{repeated}")
    assert len(chunks) == 1


def test_markdown_table_becomes_independent_table_chunk():
    text = """## 巡检记录
巡检前后应核对运行参数并填写记录。

| 项目 | 要求 |
| --- | --- |
| 压力 | 0.2–0.4MPa |
| 巡检频次 | 每2小时一次 |

巡检发现异常应及时上报。
"""
    chunks = split_structured_text(text)
    tables = [chunk for chunk in chunks if chunk.chunk_type == "table"]
    assert len(tables) == 1
    table = tables[0]
    assert table.content.startswith("| 项目 | 要求 |")
    assert "巡检发现异常" not in table.content
    assert all(
        chunk.chunk_type == "text" and not chunk.content.startswith("|")
        for chunk in chunks
        if chunk is not table
    )
    assert table.heading_path.endswith("巡检记录")


def test_markdown_table_with_blank_line_inside_keeps_single_chunk():
    text = """## 参数表
| 参数 | 范围 |
| --- | --- |

| 压力 | 0.2MPa |
后续正文说明。
"""
    chunks = split_structured_text(text)
    tables = [chunk for chunk in chunks if chunk.chunk_type == "table"]
    assert len(tables) == 1
    assert "| 压力 | 0.2MPa |" in tables[0].content


def test_long_table_split_keeps_header_in_each_piece():
    rows = "\n".join(f"| 阀门{i} | 正常状态描述内容{i} |" for i in range(60))
    text = f"## 阀门清单\n| 名称 | 状态 |\n| --- | --- |\n{rows}\n"
    chunks = split_structured_text(text, max_chars=200)
    assert len(chunks) > 1
    for chunk in chunks:
        assert chunk.chunk_type == "table"
        assert chunk.content.startswith("| 名称 | 状态 |")
        assert "| --- | --- |" in chunk.content


def test_single_page_source_has_no_page_metadata():
    text = """## 第一条 工艺流程
介质依次经过进站、分离、计量、调压和出站功能区。
"""
    chunks = split_structured_text(text)
    assert chunks
    assert all(chunk.page_start is None and chunk.page_end is None for chunk in chunks)


def test_multi_page_source_keeps_page_metadata():
    table_page = "【表格】\n| 参数 | 范围 |\n| --- | --- |\n| 压力 | 0.2MPa |"
    chunks = split_structured_text(
        "多页来源占位正文",
        pages=["# 第一章 总则\n本章说明基本要求。", table_page],
    )
    assert chunks
    assert all(chunk.page_start is not None for chunk in chunks)
    table_chunk = next(chunk for chunk in chunks if chunk.chunk_type == "table")
    assert table_chunk.page_start == 2
    # PDF 来源表格保留【表格】标记，与存量分块行为一致
    assert table_chunk.content.startswith("【表格】")
