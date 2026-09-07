"""可追溯权威知识目录加载与校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

CATALOG_PATH = Path(__file__).resolve().parents[3] / "data" / "knowledge" / "authoritative_knowledge.json"
REQUIRED_ITEM_FIELDS = {
    "knowledge_id",
    "source",
    "page",
    "chapter",
    "title",
    "content",
    "ability",
    "job_task",
    "knowledge_point",
    "skill_point",
}


def load_authoritative_knowledge(path: Path = CATALOG_PATH) -> list[dict[str, Any]]:
    """读取目录，展开来源元数据，并对可追溯字段做强校验。"""
    raw = json.loads(path.read_text(encoding="utf-8"))
    sources = raw.get("sources", {})
    items = raw.get("items", [])
    if len(items) < 50:
        raise ValueError(f"权威知识条目不足 50 条：{len(items)}")

    expanded: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, item in enumerate(items, 1):
        missing = REQUIRED_ITEM_FIELDS - item.keys()
        if missing:
            raise ValueError(f"第 {index} 条知识缺少字段：{sorted(missing)}")
        knowledge_id = str(item["knowledge_id"])
        if knowledge_id in seen:
            raise ValueError(f"知识编号重复：{knowledge_id}")
        seen.add(knowledge_id)
        source = sources.get(item["source"])
        if not source or not source.get("source_no") or not source.get("source_url"):
            raise ValueError(f"{knowledge_id} 的来源不可追溯")
        page = item.get("page")
        if page is None:
            # 无 PDF 依据的来源（如 HTML 法律全文）允许不填页码，
            # 但必须是法律来源且有条款级 chapter 定位，绝不以条目序号充数。
            if source.get("source_type") != "law" or not str(item.get("chapter", "")).strip():
                raise ValueError(
                    f"{knowledge_id} 缺少页码时必须是法律来源（source_type=law）且含条款定位"
                )
        elif not isinstance(page, int) or page < 1:
            raise ValueError(f"{knowledge_id} 的 PDF 页码无效")

        expanded.append(
            {
                **item,
                **source,
                "major": raw.get("major", "油气储运工程"),
                "position": raw.get("position", "油气管道站场运行操作岗位"),
                "difficulty": int(item.get("difficulty", 2)),
                "safety_level": item.get("safety_level", "权威来源教学摘要"),
                "tags": [*(item.get("tags") or []), f"来源链接:{source['source_url']}"],
            }
        )
    return expanded


__all__ = ["CATALOG_PATH", "load_authoritative_knowledge"]
