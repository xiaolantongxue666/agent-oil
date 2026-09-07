"""权威知识目录的数量与可追溯性测试。"""

from app.knowledge.catalog import load_authoritative_knowledge


def test_authoritative_catalog_has_50_plus_traceable_items():
    items = load_authoritative_knowledge()
    assert len(items) >= 50
    assert len({item["knowledge_id"] for item in items}) == len(items)
    for item in items:
        assert item["source_no"]
        assert item["source_name"]
        assert item["source_url"].startswith("https://")
        # 页码契约：PDF 类来源必须有真实页码；法律等 HTML 全文来源允许无页码，
        # 但必须保留条款级 chapter 定位，绝不以条目序号充当页码。
        if item["page"] is None:
            assert item["source_type"] == "law", f'{item["knowledge_id"]} 非法律来源不得缺页码'
            assert item["chapter"], f'{item["knowledge_id"]} 缺页码时必须有条款定位'
        else:
            assert isinstance(item["page"], int) and item["page"] > 0
        assert item["chapter"]
        assert item["content"]


def test_law_items_carry_no_fabricated_page():
    """LAW 条目不得保留无依据页码（修复轮契约回归）。"""
    items = load_authoritative_knowledge()
    law_items = [i for i in items if i["source_type"] == "law"]
    assert law_items, "法律条目缺失"
    for item in law_items:
        assert item["page"] is None, f'{item["knowledge_id"]} 应为无页码条款定位'
        assert "第" in item["chapter"], f'{item["knowledge_id"]} 缺条款号定位'
