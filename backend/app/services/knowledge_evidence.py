"""从岗位能力图谱关系中选择实训所需的权威知识证据。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeEvidenceRelation, KnowledgeItem
from app.models.position import Ability, KnowledgePoint
from app.models.training import TrainingTask


class KnowledgeEvidenceService:
    """按任务知识点优先、目标能力兜底，返回来源多样化的权威依据。"""

    async def get_for_task(
        self,
        db: AsyncSession,
        task: TrainingTask,
        *,
        limit: int = 8,
    ) -> list[dict[str, Any]]:
        stmt = (
            select(KnowledgeItem, KnowledgeEvidenceRelation.relevance)
            .join(
                KnowledgeEvidenceRelation,
                KnowledgeEvidenceRelation.knowledge_item_id == KnowledgeItem.id,
            )
            .join(
                KnowledgePoint,
                KnowledgePoint.id == KnowledgeEvidenceRelation.knowledge_point_id,
            )
            .join(Ability, Ability.id == KnowledgePoint.ability_id)
            .where(KnowledgeItem.safety_level == "权威来源教学摘要")
        )
        point_codes = [str(code) for code in (task.knowledge_points or []) if code]
        if point_codes:
            stmt = stmt.where(KnowledgePoint.code.in_(point_codes))
        else:
            ability_keys = [str(key) for key in (task.target_abilities or []) if key]
            if ability_keys:
                stmt = stmt.where(Ability.key.in_(ability_keys))
        stmt = stmt.order_by(KnowledgeEvidenceRelation.relevance.desc(), KnowledgeItem.id)
        rows = (await db.execute(stmt)).all()

        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for item, relevance in rows:
            buckets[item.source_type or "other"].append(self._to_evidence(item, relevance))

        # 轮询不同来源类型，避免结果被单一标准占满。
        selected: list[dict[str, Any]] = []
        source_order = ("national_occupational_standard", "law", "national_standard", "other")
        while len(selected) < limit and any(buckets.values()):
            progressed = False
            for source_type in source_order:
                if buckets[source_type] and len(selected) < limit:
                    selected.append(buckets[source_type].pop(0))
                    progressed = True
            for source_type in sorted(set(buckets) - set(source_order)):
                if buckets[source_type] and len(selected) < limit:
                    selected.append(buckets[source_type].pop(0))
                    progressed = True
            if not progressed:
                break
        return selected

    @staticmethod
    def _to_evidence(item: KnowledgeItem, relevance: float) -> dict[str, Any]:
        return {
            "knowledge_id": item.knowledge_id,
            "title": item.title,
            "content": item.content,
            "source_name": item.source_name,
            "source_no": item.source_no,
            "chapter": item.chapter,
            "page": item.page,
            "ability": item.ability,
            "knowledge_point": item.knowledge_point,
            "relevance": float(relevance),
            "is_teaching_simulation": True,
        }


__all__ = ["KnowledgeEvidenceService"]
