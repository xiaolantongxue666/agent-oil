"""读取随版本管理的公开证据目录并执行最小结构校验。"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


CATALOG_PATH = Path(__file__).with_name("verified_public_evidence.json")


def load_verified_public_evidence() -> dict[str, list[dict[str, Any]]]:
    """返回岗位与产业证据；缺少溯源字段时立即失败，避免静默写入脏数据。"""
    payload = json.loads(CATALOG_PATH.read_text(encoding="utf-8"))
    for section in ("job_postings", "industry_evidence"):
        items = payload.get(section)
        if not isinstance(items, list):
            raise ValueError(f"公开证据目录缺少列表：{section}")
        for index, item in enumerate(items, start=1):
            missing = [
                key
                for key in ("title", "source_name", "source_url", "published_at")
                if not str(item.get(key, "")).strip()
            ]
            if missing:
                raise ValueError(f"{section}[{index}] 缺少字段：{', '.join(missing)}")
    return payload


__all__ = ["load_verified_public_evidence"]
