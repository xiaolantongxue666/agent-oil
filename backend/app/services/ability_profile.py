"""能力画像服务（PHASE 9）。

每完成一次训练：
1. 获取任务的目标能力维度
2. 根据评价结果计算能力增量
3. 更新 AbilityScore（增量，不覆盖）
4. 保存 AbilityHistory（不可变历史）

六个维度：process_understanding, equipment_recognition, instrument_parameter,
         abnormal_detection, safety_awareness, standard_recording
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import AbilityKey
from app.core.logging import logger
from app.models.ability import AbilityHistory, AbilityScore
from app.models.position import Ability


@dataclass
class AbilityUpdateResult:
    """能力更新结果。"""

    ability_key: str
    ability_name: str
    before_score: float
    training_score: float
    after_score: float
    increment: float


class AbilityProfileService:
    """能力画像服务。"""

    def __init__(self, learning_rate: float = 0.15):
        """
        Args:
            learning_rate: 每次训练的能力增量系数（0-1）。
                          最终分 × learning_rate = 能力增量。
        """
        self.learning_rate = learning_rate

    async def update_from_training(
        self,
        db: AsyncSession,
        student_id: int,
        session_id: int,
        target_abilities: list[str],
        final_score: float,
        ability_scores: dict[str, float] | None = None,
    ) -> list[AbilityUpdateResult]:
        """从训练结果更新能力画像。

        Args:
            db: 数据库会话
            student_id: 学生 ID
            session_id: 训练会话 ID
            target_abilities: 任务目标能力维度 key 列表
            final_score: 最终综合评分（0-100）
            ability_scores: 按维度的评分（可选，如 {"process_understanding": 85}）
        """
        if not target_abilities:
            # 默认更新全部维度（均匀分配）
            target_abilities = [k.value for k in AbilityKey]

        results: list[AbilityUpdateResult] = []

        # 加载所有 Ability 记录（key → Ability 对象）
        ability_map = await self._load_ability_map(db)

        for ability_key in target_abilities:
            ability = ability_map.get(ability_key)
            if not ability:
                logger.warning("能力维度 {} 不存在于 abilities 表，跳过", ability_key)
                continue

            # 获取维度评分：优先 ability_scores 中的值，否则用 final_score
            dim_score = 0.0
            if ability_scores and ability_key in ability_scores:
                dim_score = float(ability_scores[ability_key])
            else:
                dim_score = final_score

            # 计算增量
            increment = dim_score * self.learning_rate

            # 获取当前 AbilityScore
            stmt = select(AbilityScore).where(
                AbilityScore.student_id == student_id,
                AbilityScore.ability_id == ability.id,
            )
            current = (await db.execute(stmt)).scalar_one_or_none()

            before_score = current.score if current else 0.0

            # 计算新分数（上限 100）
            after_score = min(100.0, before_score + increment)

            # 更新或创建 AbilityScore
            if current:
                current.score = after_score
                current.attempt_count += 1
            else:
                current = AbilityScore(
                    student_id=student_id,
                    ability_id=ability.id,
                    score=after_score,
                    attempt_count=1,
                )
                db.add(current)

            # 保存历史
            history = AbilityHistory(
                student_id=student_id,
                ability_id=ability.id,
                before_score=before_score,
                training_score=dim_score,
                after_score=after_score,
                training_session_id=session_id,
            )
            db.add(history)

            results.append(
                AbilityUpdateResult(
                    ability_key=ability_key,
                    ability_name=ability.name,
                    before_score=before_score,
                    training_score=dim_score,
                    after_score=after_score,
                    increment=round(after_score - before_score, 2),
                )
            )

        await db.flush()
        logger.info(
            "能力画像更新：student={} session={} 维度数={}",
            student_id,
            session_id,
            len(results),
        )
        return results

    async def get_profile(self, db: AsyncSession, student_id: int) -> dict[str, Any]:
        """获取学生当前能力画像（六维得分）。"""
        ability_map = await self._load_ability_map(db)

        # 加载所有 AbilityScore
        stmt = select(AbilityScore).where(AbilityScore.student_id == student_id)
        scores = (await db.execute(stmt)).scalars().all()
        score_by_ability_id = {s.ability_id: s for s in scores}

        profile: dict[str, Any] = {}
        for key in AbilityKey:
            ability = ability_map.get(key.value)
            if ability:
                score_obj = score_by_ability_id.get(ability.id)
                profile[key.value] = {
                    "name": ability.name,
                    "score": score_obj.score if score_obj else 0.0,
                    "attempt_count": score_obj.attempt_count if score_obj else 0,
                    "weight": ability.weight,
                }
        return profile

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

    async def _load_ability_map(self, db: AsyncSession) -> dict[str, Ability]:
        """加载所有 Ability（key → Ability）。"""
        stmt = select(Ability)
        abilities = (await db.execute(stmt)).scalars().all()
        return {a.key: a for a in abilities}


__all__ = ["AbilityProfileService", "AbilityUpdateResult"]
