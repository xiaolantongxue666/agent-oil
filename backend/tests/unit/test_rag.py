"""RAG 单元测试（第三十二节）。

覆盖：清洗 / 分块 / Mock Embedding / Mock Reranker / 内存存储检索 / Pipeline 检索重排 / 引用不编造。
全部离线运行（Mock + InMemoryStore）。
"""

from __future__ import annotations

import pytest

from app.rag.chunker import chunk_text
from app.rag.citation import (
    append_verified_citation_section,
    build_citation,
    format_citation_section,
    format_citation_text,
    normalize_citations,
    strip_model_citation_section,
)
from app.rag.cleaner import clean_text
from app.rag.embedding import EmbeddingService
from app.rag.pipeline import get_pipeline, reset_pipeline
from app.rag.reranker import RerankerService
from app.rag.store import InMemoryStore, reset_vector_store, set_vector_store


# ---------- 清洗 ----------
def test_clean_removes_page_numbers():
    text = "第1页\n正文内容\n12\n----\n更多正文"
    cleaned = clean_text(text)
    assert "12" not in cleaned.split("\n")
    assert "正文内容" in cleaned
    assert "更多正文" in cleaned


def test_clean_collapses_whitespace():
    assert clean_text("a   b\t\tc\n\n\n\nd") == "a b c\n\nd"


# ---------- 分块 ----------
def test_chunk_basic():
    text = "这是第一句。这是第二句。这是第三句。"
    chunks = chunk_text(text, chunk_size=20, overlap=5)
    assert len(chunks) >= 1
    assert all(c.text for c in chunks)
    assert chunks[0].chunk_index == 0


def test_chunk_empty():
    assert chunk_text("") == []


def test_chunk_preserves_overlap():
    text = "甲句。乙句。丙句。丁句。戊句。己句。庚句。辛句。壬句。癸句。"
    chunks = chunk_text(text, chunk_size=12, overlap=6)
    # 文本足够长，应至少产生 2 块
    assert len(chunks) >= 2


# ---------- Embedding Mock ----------
def test_embedding_mock_deterministic():
    svc = EmbeddingService()
    assert svc.backend == "mock"
    assert svc.dimension == 1024
    v1 = svc._mock_embed("输气站阀门渗漏")
    v2 = svc._mock_embed("输气站阀门渗漏")
    assert v1 == v2  # 确定性
    assert len(v1) == 1024


def test_embedding_mock_normalized():
    import math

    v = EmbeddingService()._mock_embed("巡检 安全 阀门")
    norm = math.sqrt(sum(x * x for x in v))
    assert abs(norm - 1.0) < 1e-6


# ---------- Reranker Mock ----------
async def test_reranker_mock_overlap():
    rr = RerankerService()
    assert rr.backend == "mock"
    scores = await rr.rerank("阀门渗漏", ["阀门渗漏检查", "无关天气"])
    assert scores[0] > scores[1]


def test_reranker_qwen3_builds_compatible_request():
    rr = RerankerService()
    rr._api_base_url = (
        "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    rr._settings.reranker_model = "qwen3-rerank"

    url, payload = rr._build_api_request("安全操作", ["风险辨识", "天气信息"])

    assert url == (
        "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks"
    )
    assert payload == {
        "model": "qwen3-rerank",
        "query": "安全操作",
        "documents": ["风险辨识", "天气信息"],
        "top_n": 2,
    }


async def test_reranker_qwen3_parses_top_level_results(monkeypatch):
    import httpx

    captured: dict[str, object] = {}

    class FakeResponse:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {
                "results": [
                    {"index": 1, "relevance_score": 0.9},
                    {"index": 0, "relevance_score": 0.2},
                ]
            }

    class FakeClient:
        def __init__(self, *, timeout: float):
            captured["timeout"] = timeout

        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc, traceback):
            return None

        async def post(self, url, *, json, headers):
            captured.update(url=url, payload=json, headers=headers)
            return FakeResponse()

    monkeypatch.setattr(httpx, "AsyncClient", FakeClient)

    rr = RerankerService()
    rr._api_key = "test-key"
    rr._api_base_url = (
        "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-mode/v1"
    )
    rr._settings.reranker_model = "qwen3-rerank"

    scores = await rr._api_rerank("安全操作", ["风险辨识", "天气信息"])

    assert scores == [0.2, 0.9]
    assert captured["url"] == (
        "https://ws-example.cn-beijing.maas.aliyuncs.com/compatible-api/v1/reranks"
    )
    assert captured["payload"] == {
        "model": "qwen3-rerank",
        "query": "安全操作",
        "documents": ["风险辨识", "天气信息"],
        "top_n": 2,
    }


# ---------- 内存存储 + Pipeline ----------
@pytest.fixture
def fresh_pipeline():
    reset_pipeline()
    reset_vector_store()
    set_vector_store(InMemoryStore())
    p = get_pipeline()
    # 预置 ready，跳过 Qdrant 探测
    p._ready = True
    yield p
    reset_pipeline()
    reset_vector_store()


async def test_pipeline_index_and_retrieve(fresh_pipeline):
    # 构造伪知识条目
    class FakeItem:
        def __init__(self, kid, content, title=""):
            self.knowledge_id = kid
            self.content = content
            self.title = title
            self.vector_embedded = False
            self.qdrant_point_id = None

        def to_payload(self):
            return {
                "knowledge_id": self.knowledge_id,
                "title": self.title,
                "source_name": "教学模拟手册",
                "source_no": "SIM-001",
                "chapter": "第三章",
                "page": 12,
                "source_type": "textbook",
                "content": self.content,
                "tags": [],
            }

    items = [
        FakeItem("K-01", "输气站阀门渗漏需要立即关闭上下游阀门并报告。", "阀门渗漏"),
        FakeItem("K-02", "天气预报显示明日有雨，注意防滑。", "天气"),
    ]
    n = await fresh_pipeline.index_knowledge(items)  # type: ignore[arg-type]
    assert n >= 2
    docs = await fresh_pipeline.retrieve_and_rerank("阀门渗漏怎么办", top_k=2)
    assert len(docs) >= 1
    assert docs[0].knowledge_id == "K-01"
    assert docs[0].rerank_score >= 0.0


# ---------- 引用不编造 ----------
def test_citation_no_fabrication():
    payload = {"knowledge_id": "K-01", "title": "阀门", "source_name": "手册", "source_no": "S-1", "chapter": "第三章", "page": 5}
    c = build_citation(payload)
    assert c["source_no"] == "S-1"
    assert c["page"] == 5
    assert c["is_teaching_simulation"] is True


def test_citation_missing_fields_empty():
    payload = {"knowledge_id": "K-02", "title": "天气"}
    c = build_citation(payload)
    assert c["source_no"] == ""
    assert c["page"] is None  # 无页码不编造
    text = format_citation_text(c)
    # 无来源名时返回空，不编造
    assert text == ""


def test_citation_text_format():
    c = {"source_name": "手册", "source_no": "S-1", "chapter": "第三章", "page": 5}
    text = format_citation_text(c)
    assert "手册" in text
    assert "S-1" in text
    assert "教学模拟" not in text


def test_citation_section_separates_source_from_teaching_usage():
    citation = {
        "knowledge_id": "NOS-003",
        "title": "埋地管道位置识别",
        "source_name": "燃气储运工国家职业技能标准（2021年版）",
        "source_no": "职业编码6-28-02-01",
        "chapter": "3.1.1 管道定位",
        "page": 12,
        "is_teaching_simulation": True,
    }

    section = format_citation_section([citation])

    assert "专业依据（系统核验）" in section
    assert "埋地管道位置识别" in section
    assert "燃气储运工国家职业技能标准（2021年版）" in section
    assert "职业编码6-28-02-01" in section
    assert "第 12 页" in section
    assert "教学模拟资料" not in section

    old_answer = "回答正文。\n\n专业依据：\n来源：教学模拟资料"
    corrected = append_verified_citation_section(old_answer, [citation])
    assert "来源：教学模拟资料" not in corrected
    assert corrected.count("专业依据（系统核验）") == 1

    rendered_again = append_verified_citation_section(corrected, [citation])
    assert rendered_again == corrected


def test_verified_citation_section_handles_heading_variants_and_bad_history():
    citation = {
        "title": "埋地管道位置识别",
        "source_name": "燃气储运工国家职业技能标准（2021年版）",
    }
    markdown_answer = "回答正文。\n\n## 专业依据\n来源：教学模拟资料"

    corrected = append_verified_citation_section(markdown_answer, [None, citation, "bad"])

    assert "来源：教学模拟资料" not in corrected
    assert "1. 埋地管道位置识别" in corrected
    assert normalize_citations({"title": "not-a-list"}) == []


def test_verified_citation_section_does_not_strip_prose_with_similar_prefix():
    answer = "专业依据：这是正文中的解释，不是依据清单标题。"
    citation = {"title": "标准", "source_name": "权威标准"}

    corrected = append_verified_citation_section(answer, [citation])

    assert answer in corrected


def test_strip_model_citation_section_removes_model_and_legacy_sections():
    # 模型自造的依据清单被剥离，正文保留
    model_answer = "回答正文。[1]\n\n**【专业依据】**\n[1] 某资料 —— 来源：教学模拟资料"
    stripped = strip_model_citation_section(model_answer)
    assert stripped == "回答正文。[1]"

    # 存量消息中旧版追加的「专业依据（系统核验）」段落与教学用途说明一并剥离
    legacy_answer = (
        "回答正文。\n\n**专业依据（系统核验）**\n"
        "1. 埋地管道位置识别；来源：燃气储运工国家职业技能标准（2021年版）\n\n"
        "*教学用途说明：以上资料用于教学模拟与脱敏学习，"
        "资料原始出处以系统核验信息为准。*"
    )
    stripped_legacy = strip_model_citation_section(legacy_answer)
    assert stripped_legacy == "回答正文。"
    assert "专业依据" not in stripped_legacy
    assert "教学用途说明" not in stripped_legacy

    # 无依据段落的回答不受影响；含相似前缀的正文不被误删
    plain = "专业依据：这是正文中的解释，不是依据清单标题。"
    assert strip_model_citation_section(plain) == plain.rstrip()


def test_citation_carries_chunk_id_when_present():
    with_chunk = build_citation({"knowledge_id": "FILE-1", "title": "块", "chunk_id": 7})
    assert with_chunk["chunk_id"] == 7
    without_chunk = build_citation({"knowledge_id": "FILE-1", "title": "条目"})
    assert without_chunk["chunk_id"] is None


# ---------- 检索块级归并 ----------
def test_merge_chunks_keeps_chunk_granularity(fresh_pipeline):
    hits = [
        {
            "id": "FILE-1-section-1",
            "score": 0.9,
            "payload": {
                "knowledge_id": "FILE-1", "chunk_id": 1,
                "title": "文件 / 甲章", "chunk_text": "块甲内容",
                "chapter": "甲章", "source_name": "标准",
            },
        },
        {
            "id": "FILE-1-section-2",
            "score": 0.8,
            "payload": {
                "knowledge_id": "FILE-1", "chunk_id": 2,
                "title": "文件 / 乙章", "chunk_text": "块乙内容",
                "chapter": "乙章",
            },
        },
        {
            "id": "FILE-1-section-1",
            "score": 0.7,
            "payload": {
                "knowledge_id": "FILE-1", "chunk_id": 1,
                "title": "文件 / 甲章", "chunk_text": "块甲内容",
                "chapter": "甲章",
            },
        },
    ]
    merged = fresh_pipeline._merge_chunks(hits)
    # 同文件不同块保持独立，重复块去重，不再拼接成「整个文件」
    assert len(merged) == 2
    values = list(merged.values())
    assert {v["chunk_id"] for v in values} == {1, 2}
    assert {v["content"] for v in values} == {"块甲内容", "块乙内容"}


# ---------- 解析层：表格渲染与页眉脚去重 ----------
def test_render_table_produces_markdown_with_marker():
    from app.rag.parser import _render_table

    rendered = _render_table([["参数", "范围"], ["压力", "0.2–0.4MPa"], [None, ""]])
    assert rendered.startswith("【表格】")
    assert "| 参数 | 范围 |" in rendered
    assert "| 压力 | 0.2–0.4MPa |" in rendered
    assert _render_table([[None, ""], [None, None]]) == ""


def test_remove_repeated_lines_strips_headers_footers():
    from app.rag.parser import _remove_repeated_lines

    pages = [
        "燃气储运工标准\n第一章 正文甲\n内容甲。",
        "燃气储运工标准\n第二章 正文乙\n内容乙。",
        "燃气储运工标准\n第三章 正文丙\n内容丙。",
        "燃气储运工标准\n第四章 正文丁\n内容丁。",
    ]
    cleaned = _remove_repeated_lines(pages)
    assert all("燃气储运工标准" not in page for page in cleaned)
    assert "第一章 正文甲" in cleaned[0]
    # 少于 3 页时不处理
    assert _remove_repeated_lines(["甲", "甲"]) == ["甲", "甲"]
