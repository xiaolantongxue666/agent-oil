"""能力画像服务（P0-1：能力水平与成长累计分离）。

统一证据流：
    任何可评分行为 → AbilityEvidence（确定性落库）
    → EMA 更新 AbilityScore.score（能力水平，可升可降）
    → 同时累计 growth_xp（成长投入，只增，与水平无关）
    → 按证据数量/来源类型数刷新 confidence（规则分档，不经 LLM）。

评分公式（参数全部来自 Settings，禁止散落写死）：
    final_score = clamp(raw_score × difficulty_weight, 0, 100)
    α_eff       = min(ability_alpha_max, ability_ema_alpha × evidence_weight × recency_weight)
    new_score   = round(old_score × (1 − α_eff) + final_score × α_eff, 2)

历史兼容：update_from_training() 保留原签名，作为选择题实训的
证据投递入口（source_type=scenario_choice），取代旧版"只涨不跌"
的线性累加（旧实现：increment = dim_score × 0.15; after = min(100, before+increment)）。
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import distinct, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.enums import AbilityKey, ConfidenceLevel, EvidenceSourceType
from app.core.logging import logger
from app.models.ability import AbilityHistory, AbilityScore
from app.models.ability_evidence import AbilityEvidence
from app.models.position import Ability


# ---------------------------------------------------------------------------
# 确定性算法核心（纯函数，无 IO，单元测试直接覆盖）
# ---------------------------------------------------------------------------


def clamp_score(value: float) -> float:
    """分值收敛到 0-100。"""
    return max(0.0, min(100.0, float(value)))


def effective_alpha(
    *,
    alpha: float,
    source_weight: float,
    recency_weight: float = 1.0,
    alpha_max: float = 0.90,
) -> float:
    """单条证据对能力水平的实际推动强度 α_eff ∈ [0, alpha_max]。

    证据来源权重越高（如 operation_event/teacher_assessment）、
    时间越新（recency_weight 越大），对 Ability Score 的影响越大。
    """
    return max(0.0, min(alpha_max, alpha * source_weight * recency_weight))


def ema_update(before: float, evidence_score: float, alpha_eff: float) -> float:
    """指数移动平均更新能力水平。

    数学性质：固定重复输入 x 时结果收敛于 x ——
    持续低分必然拉低能力，持续高分才拉高能力，不会封顶 100。
    """
    value = before * (1.0 - alpha_eff) + clamp_score(evidence_score) * alpha_eff
    return round(clamp_score(value), 2)


def confidence_for(
    *,
    evidence_count: int,
    evidence_type_count: int,
    medium_min: int = 3,
    high_min: int = 8,
    high_min_types: int = 2,
) -> str:
    """置信度规则分档（第一版刻意不用机器学习）。

    有效证据 < medium_min → LOW；
    medium_min ≤ 证据 < high_min → MEDIUM；
    证据 ≥ high_min 且来源类型 ≥ high_min_types → HIGH。
    """
    if evidence_count >= high_min and evidence_type_count >= high_min_types:
        return ConfidenceLevel.high.value
    if evidence_count >= medium_min:
        return ConfidenceLevel.medium.value
    return ConfidenceLevel.low.value


def growth_level_for(total_xp: int, level_step: int = 100) -> int:
    """成长等级 = 1 + 总 XP // 每级步长（LV 由学习投入驱动）。"""
    if total_xp <= 0 or level_step < 1:
        return 0
    return 1 + total_xp // level_step


# ---------------------------------------------------------------------------
# 服务
# ---------------------------------------------------------------------------


@dataclass
class AbilityUpdateResult:
    """单维度一次证据驱动的能力更新结果。"""

    ability_key: str
    ability_name: str
    before_score: float
    training_score: float  # 本次证据的 final_score（表现分）
    after_score: float
    increment: float  # after - before（可为负：能力会下降）
    confidence: str = ConfidenceLevel.low.value
    evidence_count: int = 0
    growth_xp: int = 0


class AbilityProfileService:
    """能力画像服务：证据 → EMA 能力水平 + Growth XP + Confidence。"""

    async def record_evidence(
        self,
        db: AsyncSession,
        *,
        student_id: int,
        ability_key: str,
        source_type: EvidenceSourceType | str,
        raw_score: float,
        source_id: int | None = None,
        session_id: int | None = None,
        difficulty_weight: float = 1.0,
        recency_weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
        write_history: bool = True,
    ) -> AbilityUpdateResult | None:
        """记录一条能力证据并按确定性规则更新画像。

        Args:
            db: 数据库会话
            student_id: 学生 ID
            ability_key: 能力维度键（六维之一）
            source_type: 证据来源类型（EvidenceSourceType）
            raw_score: 原始表现分 0-100（超过会被 clamp）
            source_id: 来源对象 ID（题目/会话/评价记录，多态，仅存证）
            session_id: 关联训练会话 ID（仅写 AbilityHistory 外键用）
            difficulty_weight: 难度系数（>1 放大表现分，默认 1.0）
            recency_weight: 时间衰减（第一版恒 1.0，预留）
            metadata: 附加上下文（题目 ID、场景编码等）
            write_history: 是否写 AbilityHistory（默认写）

        Returns:
            更新结果；ability_key 不存在于 abilities 表时返回 None（记 warning）。
            未知 source_type 直接抛 ValueError（fail-loud，不静默用错权重）。
        """
        settings = get_settings()
        source = source_type.value if isinstance(source_type, EvidenceSourceType) else str(source_type)
        weight = settings.ability_evidence_weight(source)  # 未知类型抛 ValueError

        ability_map = await self._load_ability_map(db)
        ability = ability_map.get(ability_key)
        if ability is None:
            logger.warning("能力维度 {} 不存在于 abilities 表，跳过证据记录", ability_key)
            return None

        raw = round(clamp_score(raw_score), 2)
        difficulty = max(0.0, float(difficulty_weight))
        final_score = round(clamp_score(raw * difficulty), 2)

        evidence = AbilityEvidence(
            student_id=student_id,
            ability_key=ability_key,
            source_type=source,
            source_id=source_id,
            raw_score=raw,
            evidence_weight=weight,
            difficulty_weight=difficulty,
            recency_weight=float(recency_weight),
            final_score=final_score,
            metadata_json=metadata or {},
        )
        db.add(evidence)
        await db.flush()  # 让同事务内的证据计数查询能看见本条

        current = await self._get_or_create_score(db, student_id, ability.id)
        before = float(current.score)

        alpha_eff = effective_alpha(
            alpha=settings.ability_ema_alpha,
            source_weight=weight,
            recency_weight=recency_weight,
            alpha_max=settings.ability_alpha_max,
        )
        after = ema_update(before, final_score, alpha_eff)

        current.score = after
        current.attempt_count += 1
        current.growth_xp += max(1, round(settings.ability_xp_base_per_evidence * weight))

        evidence_count, evidence_type_count = await self._count_evidence(db, student_id, ability_key)
        current.evidence_count = evidence_count
        current.evidence_type_count = evidence_type_count
        current.confidence = confidence_for(
            evidence_count=evidence_count,
            evidence_type_count=evidence_type_count,
            medium_min=settings.ability_confidence_medium_min,
            high_min=settings.ability_confidence_high_min,
            high_min_types=settings.ability_confidence_high_min_types,
        )
        current.last_evaluated_at = datetime.now(UTC)

        if write_history:
            db.add(
                AbilityHistory(
                    student_id=student_id,
                    ability_id=ability.id,
                    before_score=before,
                    training_score=final_score,
                    after_score=after,
                    training_session_id=session_id,
                )
            )

        await db.flush()
        logger.info(
            "能力证据落库：student={} ability={} source={} raw={} → score {}→{} conf={}",
            student_id,
            ability_key,
            source,
            raw,
            before,
            after,
            current.confidence,
        )
        return AbilityUpdateResult(
            ability_key=ability_key,
            ability_name=ability.name,
            before_score=before,
            training_score=final_score,
            after_score=after,
            increment=round(after - before, 2),
            confidence=current.confidence,
            evidence_count=evidence_count,
            growth_xp=current.growth_xp,
        )

    async def update_from_training(
        self,
        db: AsyncSession,
        student_id: int,
        session_id: int,
        target_abilities: list[str],
        final_score: float,
        ability_scores: dict[str, float] | None = None,
    ) -> list[AbilityUpdateResult]:
        """从选择题实训结果投递能力证据（兼容旧入口，签名不变）。

        每个目标维度生成一条 source_type=scenario_choice 的证据；
        维度分优先取 ability_scores，缺省用整卷 final_score。
        """
        if not target_abilities:
            # 默认更新全部维度
            target_abilities = [k.value for k in AbilityKey]

        results: list[AbilityUpdateResult] = []
        for ability_key in target_abilities:
            dim_score = float(final_score)
            if ability_scores and ability_key in ability_scores:
                dim_score = float(ability_scores[ability_key])
            result = await self.record_evidence(
                db,
                student_id=student_id,
                ability_key=ability_key,
                source_type=EvidenceSourceType.scenario_choice,
                raw_score=dim_score,
                source_id=session_id,
                session_id=session_id,
                metadata={"source": "choice_training", "final_score": final_score},
            )
            if result:
                results.append(result)

        logger.info(
            "能力画像更新：student={} session={} 维度数={}",
            student_id,
            session_id,
            len(results),
        )
        return results

    async def get_profile(self, db: AsyncSession, student_id: int) -> dict[str, Any]:
        """获取学生当前能力画像（六维：水平 + 置信度 + 证据 + XP）。

        注意：返回值保持"六个能力键 → dict"的结构（集成测试与前端依赖），
        学生级成长汇总请走 get_growth()。
        """
        ability_map = await self._load_ability_map(db)

        stmt = select(AbilityScore).where(AbilityScore.student_id == student_id)
        scores = (await db.execute(stmt)).scalars().all()
        score_by_ability_id = {s.ability_id: s for s in scores}

        profile: dict[str, Any] = {}
        for key in AbilityKey:
            ability = ability_map.get(key.value)
            if ability:
                obj = score_by_ability_id.get(ability.id)
                profile[key.value] = {
                    "name": ability.name,
                    "score": obj.score if obj else 0.0,
                    "attempt_count": obj.attempt_count if obj else 0,
                    "weight": ability.weight,
                    "growth_xp": obj.growth_xp if obj else 0,
                    "confidence": obj.confidence if obj else ConfidenceLevel.low.value,
                    "evidence_count": obj.evidence_count if obj else 0,
                    "evidence_type_count": obj.evidence_type_count if obj else 0,
                    "last_evaluated_at": (
                        obj.last_evaluated_at.isoformat()
                        if obj and obj.last_evaluated_at
                        else None
                    ),
                }
        return profile

    async def get_growth(self, db: AsyncSession, student_id: int) -> dict[str, Any]:
        """学生级成长汇总（Growth XP / Level），由各维 XP 求和派生。"""
        settings = get_settings()
        stmt = select(AbilityScore).where(AbilityScore.student_id == student_id)
        scores = (await db.execute(stmt)).scalars().all()
        ability_map = await self._load_ability_map(db)
        id_to_key = {a.id: k for k, a in ability_map.items()}

        per_ability = {
            id_to_key.get(s.ability_id, ""): s.growth_xp for s in scores if id_to_key.get(s.ability_id)
        }
        total_xp = sum(s.growth_xp for s in scores)
        return {
            "total_xp": total_xp,
            "growth_level": growth_level_for(total_xp, settings.ability_xp_level_step),
            "xp_level_step": settings.ability_xp_level_step,
            "per_ability": per_ability,
            "total_evidence": sum(s.evidence_count for s in scores),
        }

    async def get_evidence(
        self,
        db: AsyncSession,
        student_id: int,
        ability_key: str | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """证据档案：单条证据时间线 + 来源类型汇总。"""
        conditions = [AbilityEvidence.student_id == student_id]
        if ability_key:
            conditions.append(AbilityEvidence.ability_key == ability_key)

        stmt = (
            select(AbilityEvidence)
            .where(*conditions)
            .order_by(AbilityEvidence.created_at.desc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).scalars().all()

        items = [
            {
                "id": e.id,
                "ability_key": e.ability_key,
                "source_type": e.source_type,
                "source_id": e.source_id,
                "raw_score": e.raw_score,
                "evidence_weight": e.evidence_weight,
                "difficulty_weight": e.difficulty_weight,
                "final_score": e.final_score,
                "metadata": e.metadata_json or {},
                "created_at": e.created_at.isoformat() if e.created_at else None,
            }
            for e in rows
        ]
        by_type: dict[str, int] = {}
        for item in items:
            by_type[item["source_type"]] = by_type.get(item["source_type"], 0) + 1
        return {"items": items, "total_returned": len(items), "by_source_type": by_type}

    async def get_history(
        self,
        db: AsyncSession,
        student_id: int,
        ability_key: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        """获取能力变更历史。"""
        ability_map = await self._load_ability_map(db)

        stmt = (
            select(AbilityHistory)
            .where(AbilityHistory.student_id == student_id)
            .order_by(AbilityHistory.created_at.desc())
            .limit(limit)
        )
        if ability_key and ability_key in ability_map:
            ability_id = ability_map[ability_key].id
            stmt = stmt.where(AbilityHistory.ability_id == ability_id)

        histories = (await db.execute(stmt)).scalars().all()
        result = []
        for h in histories:
            ability = next((a for a in ability_map.values() if a.id == h.ability_id), None)
            result.append(
                {
                    "id": h.id,
                    "ability_key": ability.key if ability else "",
                    "ability_name": ability.name if ability else "",
                    "before_score": h.before_score,
                    "training_score": h.training_score,
                    "after_score": h.after_score,
                    "training_session_id": h.training_session_id,
                    "created_at": h.created_at.isoformat() if h.created_at else "",
                }
            )
        return result

    async def get_radar_data(self, db: AsyncSession, student_id: int) -> dict[str, Any]:
        """获取雷达图数据（六维当前得分 + 能力名称）。"""
        profile = await self.get_profile(db, student_id)
        labels = []
        scores = []
        max_scores = []
        for key in AbilityKey:
            dim = profile.get(key.value, {})
            labels.append(dim.get("name", key.value))
            scores.append(dim.get("score", 0))
            max_scores.append(100)
        return {
            "labels": labels,
            "scores": scores,
            "max_scores": max_scores,
            "indicators": [{"name": lbl, "max": 100} for lbl in labels],
        }

    async def _get_or_create_score(
        self, db: AsyncSession, student_id: int, ability_id: int
    ) -> AbilityScore:
        stmt = select(AbilityScore).where(
            AbilityScore.student_id == student_id,
            AbilityScore.ability_id == ability_id,
        )
        current = (await db.execute(stmt)).scalar_one_or_none()
        if current is None:
            current = AbilityScore(
                student_id=student_id,
                ability_id=ability_id,
                score=0.0,
                attempt_count=0,
            )
            db.add(current)
            await db.flush()
        return current

    async def _count_evidence(
        self, db: AsyncSession, student_id: int, ability_key: str
    ) -> tuple[int, int]:
        """(证据条数, 证据来源类型数)。"""
        stmt = select(
            func.count(AbilityEvidence.id),
            func.count(distinct(AbilityEvidence.source_type)),
        ).where(
            AbilityEvidence.student_id == student_id,
            AbilityEvidence.ability_key == ability_key,
        )
        row = (await db.execute(stmt)).one()
        return int(row[0]), int(row[1])

    async def _load_ability_map(self, db: AsyncSession) -> dict[str, Ability]:
        """加载所有 Ability（key → Ability）。"""
        stmt = select(Ability)
        abilities = (await db.execute(stmt)).scalars().all()
        return {a.key: a for a in abilities}


__all__ = [
    "AbilityProfileService",
    "AbilityUpdateResult",
    "clamp_score",
    "confidence_for",
    "effective_alpha",
    "ema_update",
    "growth_level_for",
]
