"""推荐引擎服务（PHASE 10）。

规则推荐 + 能力匹配：
1. 读取六维能力
2. 找到最低能力（薄弱项）
3. 查询相关知识点
4. 查询对应实训任务
5. 判断当前难度
6. 推荐下一任务

推荐逻辑由代码完成。AI 负责将推荐理由转换成自然语言（可选）。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TaskStatus
from app.models.ability import AbilityScore
from app.models.position import Ability
from app.models.training import TrainingSession, TrainingTask


@dataclass
class RecommendationItem:
    """单条推荐结果。"""

    task_id: int
    task_code: str
    task_title: str
    target_ability: str
    target_ability_name: str
    reason_code: str = "weak_ability"
    reason_text: str = ""
    difficulty: int = 2
    estimated_minutes: int = 15
    current_ability_score: float = 0.0


class RecommendationService:
    """规则推荐引擎。"""

    def __init__(self, weak_threshold: float = 60.0, max_recommendations: int = 5):
        self.weak_threshold = weak_threshold
        self.max_recommendations = max_recommendations

    async def generate_recommendations(
        self,
        db: AsyncSession,
        student_id: int,
    ) -> list[RecommendationItem]:
        """为学生生成个性化推荐。"""
        # 1. 获取六维能力
        ability_scores = await self._get_ability_scores(db, student_id)

        if not ability_scores:
            # 无能力数据：推荐入门任务
            recommendations = await self._recommend_beginner_tasks(db, student_id)
            if recommendations:
                return recommendations
            completed_task_ids = await self._get_completed_task_ids(db, student_id)
            return await self._recommend_retry_tasks(db, completed_task_ids, {})

        # 2. 找薄弱能力
        weak_abilities = self._find_weak_abilities(ability_scores)

        if not weak_abilities:
            # 无薄弱项：推荐进阶任务
            recommendations = await self._recommend_advanced_tasks(
                db, student_id, ability_scores
            )
            if recommendations:
                return recommendations
            completed_task_ids = await self._get_completed_task_ids(db, student_id)
            return await self._recommend_retry_tasks(
                db,
                completed_task_ids,
                ability_scores,
            )

        # 3. 为每个薄弱能力找推荐任务
        recommendations: list[RecommendationItem] = []
        completed_task_ids = await self._get_completed_task_ids(db, student_id)

        for ability_key, score_info in weak_abilities:
            if len(recommendations) >= self.max_recommendations:
                break

            tasks = await self._find_tasks_for_ability(db, ability_key)
            for task in tasks:
                if task.id in completed_task_ids:
                    continue
                if len(recommendations) >= self.max_recommendations:
                    break

                # 难度匹配：当前能力分越低，推荐越简单的任务
                target_difficulty = self._calculate_target_difficulty(score_info["score"])
                if abs(task.difficulty - target_difficulty) > 2:
                    continue

                reason = self._generate_reason(ability_key, score_info, task)
                recommendations.append(
                    RecommendationItem(
                        task_id=task.id,
                        task_code=task.code,
                        task_title=task.title,
                        target_ability=ability_key,
                        target_ability_name=score_info["name"],
                        reason_code="weak_ability",
                        reason_text=reason,
                        difficulty=task.difficulty,
                        estimated_minutes=task.estimated_minutes,
                        current_ability_score=score_info["score"],
                    )
                )

        # 4. 如果推荐不足，补充未完成的低难度任务
        if len(recommendations) < self.max_recommendations:
            extra = await self._fill_remaining_tasks(
                db, student_id, completed_task_ids, recommendations
            )
            recommendations.extend(extra)

        # 所有已发布任务都完成时，给出针对薄弱能力的复训建议，
        # 避免“推荐功能执行成功但结果为空”。复训不会覆盖历史训练记录。
        if not recommendations and completed_task_ids:
            recommendations = await self._recommend_retry_tasks(
                db,
                completed_task_ids,
                ability_scores,
            )

        return recommendations

    async def _recommend_retry_tasks(
        self,
        db: AsyncSession,
        completed_task_ids: set[int],
        ability_scores: dict[str, dict[str, Any]],
    ) -> list[RecommendationItem]:
        """从已完成且仍发布的任务中选择一个薄弱能力复训项。"""

        if not completed_task_ids:
            return []
        tasks = (
            await db.execute(
                select(TrainingTask).where(
                    TrainingTask.id.in_(completed_task_ids),
                    TrainingTask.status == TaskStatus.published,
                )
            )
        ).scalars().all()
        if not tasks:
            return []

        ranked_abilities = sorted(
            ability_scores.items(),
            key=lambda item: float(item[1].get("score", 0.0)),
        )
        ability_rank = {key: index for index, (key, _) in enumerate(ranked_abilities)}

        def _task_rank(task: TrainingTask) -> tuple[int, int, int]:
            targets = task.target_abilities or []
            weakest_rank = min(
                (ability_rank.get(str(key), len(ability_rank)) for key in targets),
                default=len(ability_rank),
            )
            return weakest_rank, task.difficulty, task.id

        task = min(tasks, key=_task_rank)
        target_key = min(
            (str(key) for key in (task.target_abilities or [])),
            key=lambda key: ability_rank.get(key, len(ability_rank)),
            default=(ranked_abilities[0][0] if ranked_abilities else ""),
        )
        score_info = ability_scores.get(target_key, {})
        target_name = str(score_info.get("name", "综合能力"))
        current_score = float(score_info.get("score", 0.0))
        reason = (
            f"【教学模拟】当前没有未完成的已发布实训。"
            f"建议复训「{task.title}」，继续强化「{target_name}」能力。"
        )
        return [
            RecommendationItem(
                task_id=task.id,
                task_code=task.code,
                task_title=task.title,
                target_ability=target_key,
                target_ability_name=target_name,
                reason_code="retry",
                reason_text=reason,
                difficulty=task.difficulty,
                estimated_minutes=task.estimated_minutes,
                current_ability_score=current_score,
            )
        ]

    async def _get_ability_scores(
        self, db: AsyncSession, student_id: int
    ) -> dict[str, dict[str, Any]]:
        """获取学生六维能力得分。"""
        stmt = select(Ability).order_by(Ability.id)
        abilities = (await db.execute(stmt)).scalars().all()

        stmt2 = select(AbilityScore).where(AbilityScore.student_id == student_id)
        scores = (await db.execute(stmt2)).scalars().all()
        score_map = {s.ability_id: s.score for s in scores}

        result = {}
        for a in abilities:
            result[a.key] = {
                "name": a.name,
                "score": score_map.get(a.id, 0.0),
                "weight": a.weight,
            }
        return result

    def _find_weak_abilities(
        self, ability_scores: dict[str, dict[str, Any]]
    ) -> list[tuple[str, dict[str, Any]]]:
        """找到低于阈值的薄弱能力，按分数升序排列。"""
        weak = [
            (key, info)
            for key, info in ability_scores.items()
            if info["score"] < self.weak_threshold
        ]
        weak.sort(key=lambda x: x[1]["score"])
        return weak

    async def _find_tasks_for_ability(
        self, db: AsyncSession, ability_key: str
    ) -> list[TrainingTask]:
        """查找针对某能力维度的训练任务。"""
        stmt = select(TrainingTask).where(
            TrainingTask.status == TaskStatus.published
        )
        tasks = (await db.execute(stmt)).scalars().all()
        # 筛选 target_abilities 包含该维度的任务
        matched = [
            t
            for t in tasks
            if ability_key in (t.target_abilities or [])
        ]
        # 按难度排序
        matched.sort(key=lambda t: t.difficulty)
        return matched

    async def _get_completed_task_ids(
        self, db: AsyncSession, student_id: int
    ) -> set[int]:
        """获取学生已完成的任务 ID 集合。"""
        stmt = (
            select(TrainingSession.task_id)
            .where(
                TrainingSession.student_id == student_id,
                TrainingSession.finished == True,  # noqa: E712
            )
            .distinct()
        )
        result = (await db.execute(stmt)).scalars().all()
        return set(result)

    def _calculate_target_difficulty(self, current_score: float) -> int:
        """根据当前能力分计算推荐难度（1-5）。"""
        if current_score < 20:
            return 1
        elif current_score < 40:
            return 2
        elif current_score < 60:
            return 3
        elif current_score < 80:
            return 4
        else:
            return 5

    def _generate_reason(
        self, ability_key: str, score_info: dict, task: TrainingTask
    ) -> str:
        """生成推荐理由。"""
        name = score_info["name"]
        score = score_info["score"]
        return (
            f"【教学模拟】你在「{name}」维度得分为 {score:.0f}，"
            f"低于推荐阈值 {self.weak_threshold:.0f}。"
            f"建议通过「{task.title}」(难度 {task.difficulty}) 加强训练。"
        )

    async def _recommend_beginner_tasks(
        self, db: AsyncSession, student_id: int
    ) -> list[RecommendationItem]:
        """无能力数据时推荐入门任务。"""
        completed = await self._get_completed_task_ids(db, student_id)
        stmt = (
            select(TrainingTask)
            .where(TrainingTask.status == TaskStatus.published, TrainingTask.difficulty <= 2)
            .order_by(TrainingTask.difficulty, TrainingTask.id)
            .limit(self.max_recommendations)
        )
        tasks = (await db.execute(stmt)).scalars().all()
        recommendations = []
        for t in tasks:
            if t.id not in completed:
                recommendations.append(
                    RecommendationItem(
                        task_id=t.id,
                        task_code=t.code,
                        task_title=t.title,
                        target_ability=(t.target_abilities or [""])[0],
                        target_ability_name="综合能力",
                        reason_code="beginner",
                        reason_text="【教学模拟】作为新手入门训练推荐。",
                        difficulty=t.difficulty,
                        estimated_minutes=t.estimated_minutes,
                    )
                )
        return recommendations[: self.max_recommendations]

    async def _recommend_advanced_tasks(
        self,
        db: AsyncSession,
        student_id: int,
        ability_scores: dict[str, dict],
    ) -> list[RecommendationItem]:
        """无薄弱项时推荐进阶任务。"""
        completed = await self._get_completed_task_ids(db, student_id)
        stmt = (
            select(TrainingTask)
            .where(TrainingTask.status == TaskStatus.published, TrainingTask.difficulty >= 3)
            .order_by(TrainingTask.difficulty.desc(), TrainingTask.id)
            .limit(self.max_recommendations * 2)
        )
        tasks = (await db.execute(stmt)).scalars().all()
        recommendations = []
        for t in tasks:
            if t.id not in completed and len(recommendations) < self.max_recommendations:
                recommendations.append(
                    RecommendationItem(
                        task_id=t.id,
                        task_code=t.code,
                        task_title=t.title,
                        target_ability=(t.target_abilities or [""])[0],
                        target_ability_name="进阶训练",
                        reason_code="advanced",
                        reason_text="【教学模拟】能力均衡，推荐进阶挑战。",
                        difficulty=t.difficulty,
                        estimated_minutes=t.estimated_minutes,
                    )
                )
        return recommendations

    async def _fill_remaining_tasks(
        self,
        db: AsyncSession,
        student_id: int,
        completed_task_ids: set[int],
        existing: list[RecommendationItem],
    ) -> list[RecommendationItem]:
        """补充推荐未完成的任务。"""
        existing_ids = {r.task_id for r in existing}
        stmt = (
            select(TrainingTask)
            .where(TrainingTask.status == TaskStatus.published)
            .order_by(TrainingTask.difficulty, TrainingTask.id)
        )
        tasks = (await db.execute(stmt)).scalars().all()
        extra = []
        for t in tasks:
            if t.id not in completed_task_ids and t.id not in existing_ids:
                if len(existing) + len(extra) >= self.max_recommendations:
                    break
                extra.append(
                    RecommendationItem(
                        task_id=t.id,
                        task_code=t.code,
                        task_title=t.title,
                        target_ability=(t.target_abilities or [""])[0],
                        target_ability_name="综合训练",
                        reason_code="uncompleted",
                        reason_text="【教学模拟】尚未完成的训练任务。",
                        difficulty=t.difficulty,
                        estimated_minutes=t.estimated_minutes,
                    )
                )
        return extra


__all__ = ["RecommendationService", "RecommendationItem"]
