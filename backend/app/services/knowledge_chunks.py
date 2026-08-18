"""上传文件的章节分块、知识点建议和图谱关系同步。"""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import KnowledgeChunk, KnowledgeEvidenceRelation, KnowledgeItem
from app.models.position import Ability, KnowledgePoint
from app.rag.structured_chunker import StructuredTextChunk, split_structured_text

_IRRELEVANT_HEADINGS = (
    "目录",
    "前言",
    "序言",
    "参考文献",
    "编制说明",
    "版权",
    "封面",
)
_PROFESSIONAL_KEYWORDS = (
    "油气",
    "燃气",
    "储运",
    "输气",
    "管道",
    "站场",
    "阀门",
    "压力",
    "温度",
    "流量",
    "设备",
    "仪表",
    "巡检",
    "安全",
    "风险",
    "泄漏",
    "消防",
    "作业",
    "记录",
    "报告",
    "职业技能",
)
# MD/TXT 等单页来源没有真实页码，分块不填充 page_start/page_end
_SINGLE_PAGE_FILE_TYPES = ("txt", "md", "markdown")
_POINT_KEYWORDS: dict[str, tuple[str, ...]] = {
    "K-PROC-01": ("工艺流程", "介质流向", "进站", "出站", "分离", "计量", "调压"),
    "K-PROC-02": ("功能区", "设备组成", "设备作用", "工艺区"),
    "K-EQP-01": ("阀门类型", "球阀", "闸阀", "截止阀", "止回阀", "安全阀"),
    "K-EQP-02": ("阀门状态", "阀位", "内漏", "外漏", "密封"),
    "K-EQP-03": ("离心泵", "往复泵", "泵体", "泵类"),
    "K-EQP-04": ("压缩机", "压缩机组", "往复式", "离心式"),
    "K-INS-01": ("压力表", "压力仪表", "压力读数", "量程"),
    "K-INS-02": ("温度仪表", "温度计", "温度读数", "温升"),
    "K-INS-03": ("流量计", "流量仪表", "流量读数", "流量单位"),
    "K-ABN-01": ("参数偏离", "压力异常", "流量异常", "设定值"),
    "K-ABN-02": ("设备异常", "振动", "异响", "异常温升"),
    "K-ABN-03": ("趋势", "突变", "渐变", "历史数据"),
    "K-SAF-01": ("泄漏风险", "法兰泄漏", "阀门泄漏", "管段泄漏"),
    "K-SAF-02": ("HSE", "风险辨识", "防护措施", "受限空间", "动火", "临时用电"),
    "K-SAF-03": ("消防设施", "灭火器", "消防水", "灭火系统"),
    "K-REC-01": ("巡检记录", "记录要素", "填写规范", "运行记录"),
    "K-REC-02": ("异常报告", "异常上报", "报告流程", "信息报告"),
}


@dataclass(slots=True)
class ChunkSuggestion:
    enabled: bool
    knowledge_point_id: int | None
    knowledge_point_code: str
    knowledge_point_name: str
    ability: str
    score: float
    reason: str


async def create_chunks_for_item(
    session: AsyncSession,
    item: KnowledgeItem,
    *,
    pages: list[str] | None = None,
) -> list[KnowledgeChunk]:
    """为文件知识条目创建可审核章节块；已存在时直接返回。"""
    existing = (
        await session.scalars(
            select(KnowledgeChunk)
            .where(KnowledgeChunk.knowledge_item_id == item.id)
            .order_by(KnowledgeChunk.chunk_index)
        )
    ).all()
    if existing:
        return list(existing)

    point_rows = (
        await session.execute(
            select(KnowledgePoint, Ability.key).join(
                Ability, Ability.id == KnowledgePoint.ability_id
            )
        )
    ).all()
    structured = split_structured_text(item.content, pages=pages)
    chunks: list[KnowledgeChunk] = []
    for source in structured:
        suggestion = suggest_chunk(source, point_rows, preferred_ability=item.ability)
        chunk = KnowledgeChunk(
            knowledge_item_id=item.id,
            chunk_index=source.chunk_index,
            heading=source.heading,
            chapter=source.chapter,
            heading_path=source.heading_path,
            chunk_type=source.chunk_type,
            content=source.content,
            page_start=source.page_start,
            page_end=source.page_end,
            char_start=source.char_start,
            char_end=source.char_end,
            checksum=source.checksum,
            knowledge_point_id=suggestion.knowledge_point_id,
            knowledge_point_code=suggestion.knowledge_point_code,
            knowledge_point_name=suggestion.knowledge_point_name,
            ability=suggestion.ability or item.ability,
            match_score=suggestion.score,
            match_reason=suggestion.reason,
            enabled=suggestion.enabled,
        )
        session.add(chunk)
        chunks.append(chunk)
    item.vector_embedded = False
    item.qdrant_point_id = None
    await session.flush()
    await sync_item_evidence_relations(session, item.id)
    return chunks


def suggest_chunk(
    chunk: StructuredTextChunk,
    point_rows: list[tuple[KnowledgePoint, str]],
    *,
    preferred_ability: str,
) -> ChunkSuggestion:
    """基于专业关键词给出启用和知识点映射建议，最终由教师确认。"""
    text = f"{chunk.heading}\n{chunk.content}"
    irrelevant = any(word in chunk.heading for word in _IRRELEVANT_HEADINGS)
    professional_hits = [word for word in _PROFESSIONAL_KEYWORDS if word.lower() in text.lower()]

    best_point: KnowledgePoint | None = None
    best_ability = ""
    best_hits: list[str] = []
    best_score = 0.0
    for point, ability_key in point_rows:
        keywords = (point.name, *_POINT_KEYWORDS.get(point.code, ()))
        hits = [word for word in keywords if word and word.lower() in text.lower()]
        score = float(len(set(hits)))
        if point.name and point.name in text:
            score += 2.0
        if score > 0 and ability_key == preferred_ability:
            score += 0.25
        if score > best_score:
            best_point = point
            best_ability = ability_key
            best_hits = hits
            best_score = score

    enabled = (
        not irrelevant
        and len(chunk.content.strip()) >= 30
        and best_point is not None
        and best_score >= 1.0
    )
    if irrelevant:
        reason = "疑似目录/前言等非知识正文，建议停用"
    elif best_point is not None:
        reason = f"命中知识点关键词：{', '.join(best_hits[:4]) or best_point.name}"
    elif professional_hits:
        reason = f"命中专业词：{', '.join(professional_hits[:4])}；待教师选择知识点"
    else:
        reason = "未识别到专业知识点，建议停用"

    return ChunkSuggestion(
        enabled=enabled,
        knowledge_point_id=best_point.id if best_point else None,
        knowledge_point_code=best_point.code if best_point else "",
        knowledge_point_name=best_point.name if best_point else "",
        ability=best_ability or preferred_ability,
        score=round(best_score, 2),
        reason=reason,
    )


async def sync_item_evidence_relations(session: AsyncSession, item_id: int) -> None:
    """按已启用且已映射的文件块重建该文件的图谱支撑关系。"""
    await session.execute(
        delete(KnowledgeEvidenceRelation).where(
            KnowledgeEvidenceRelation.knowledge_item_id == item_id
        )
    )
    point_ids = set(
        (
            await session.scalars(
                select(KnowledgeChunk.knowledge_point_id).where(
                    KnowledgeChunk.knowledge_item_id == item_id,
                    KnowledgeChunk.enabled.is_(True),
                    KnowledgeChunk.knowledge_point_id.is_not(None),
                )
            )
        ).all()
    )
    for point_id in point_ids:
        if point_id is not None:
            session.add(
                KnowledgeEvidenceRelation(
                    knowledge_point_id=point_id,
                    knowledge_item_id=item_id,
                    relation_type="supports",
                    relevance=0.9,
                )
            )
    await session.flush()


async def backfill_file_chunks(session: AsyncSession) -> int:
    """为历史文件导入记录补建章节块，正文不重复入库。"""
    items = (
        await session.scalars(
            select(KnowledgeItem).where(KnowledgeItem.source_type == "file_import")
        )
    ).all()
    created = 0
    for item in items:
        existing_chunks = list(
            (
                await session.scalars(
                    select(KnowledgeChunk)
                    .where(KnowledgeChunk.knowledge_item_id == item.id)
                    .order_by(KnowledgeChunk.chunk_index)
                )
            ).all()
        )
        if not existing_chunks:
            chunks = await create_chunks_for_item(session, item)
            created += len(chunks)
        else:
            # 单页来源清空历史伪造的"第1页"（展示元数据，不影响教师审核状态）
            if item.file_type in _SINGLE_PAGE_FILE_TYPES:
                for chunk in existing_chunks:
                    if chunk.page_start is not None or chunk.page_end is not None:
                        chunk.page_start = None
                        chunk.page_end = None
            point_rows = (
                await session.execute(
                    select(KnowledgePoint, Ability.key).join(
                        Ability, Ability.id == KnowledgePoint.ability_id
                    )
                )
            ).all()
            for chunk in existing_chunks:
                if chunk.reviewed:
                    continue
                suggestion = suggest_chunk(
                    StructuredTextChunk(
                        chunk_index=chunk.chunk_index,
                        heading=chunk.heading,
                        chapter=chunk.chapter,
                        content=chunk.content,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        char_start=chunk.char_start,
                        char_end=chunk.char_end,
                        checksum=chunk.checksum,
                    ),
                    point_rows,
                    preferred_ability=item.ability,
                )
                chunk.enabled = suggestion.enabled
                chunk.knowledge_point_id = suggestion.knowledge_point_id
                chunk.knowledge_point_code = suggestion.knowledge_point_code
                chunk.knowledge_point_name = suggestion.knowledge_point_name
                chunk.ability = suggestion.ability
                chunk.match_score = suggestion.score
                chunk.match_reason = suggestion.reason
                chunk.vector_embedded = False
                chunk.qdrant_point_id = None
            item.vector_embedded = False
            item.qdrant_point_id = None
            await sync_item_evidence_relations(session, item.id)
    return created


__all__ = [
    "backfill_file_chunks",
    "create_chunks_for_item",
    "suggest_chunk",
    "sync_item_evidence_relations",
]
