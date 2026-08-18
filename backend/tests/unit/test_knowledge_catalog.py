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
        assert isinstance(item["page"], int) and item["page"] > 0
        assert item["chapter"]
        assert item["content"]
