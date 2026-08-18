"""根据学生选择题实训明细动态生成个人自适应学习路径。"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.enums import TaskStatus
from app.models.ability import AbilityScore
from app.models.position import Ability
from app.models.training import (
    TrainingChoiceAnswer,
    TrainingQuestion,
    TrainingSession,
    TrainingTask,
)


class AdaptiveLearningService:
    """学生层闭环；不产生或修改专业培养方案。"""

    async def build_path(self, db: AsyncSession, student_id: int) -> dict[str, Any]:
        answer_rows = list(
            (
                await db.execute(
                    select(TrainingChoiceAnswer, TrainingQuestion)
                    .join(TrainingQuestion, TrainingQuestion.id == TrainingChoiceAnswer.question_id)
                    .join(TrainingSession, TrainingSession.id == TrainingChoiceAnswer.session_id)
                    .where(
                        TrainingSession.student_id == student_id,
                        TrainingSession.finished == True,  # noqa: E712
                    )
                    .order_by(TrainingChoiceAnswer.created_at, TrainingChoiceAnswer.id)
                )
            ).all()
        )
        abilities = (await db.execute(select(Ability).order_by(Ability.id))).scalars().all()
        score_rows = (
            await db.execute(select(AbilityScore).where(AbilityScore.student_id == student_id))
        ).scalars().all()
        score_map = {item.ability_id: item for item in score_rows}
        ability_state = [
            {
                "key": ability.key,
                "name": ability.name,
                "score": round(score_map.get(ability.id).score, 1) if ability.id in score_map else 0,
                "attempt_count": score_map.get(ability.id).attempt_count if ability.id in score_map else 0,
                "state": self._state(round(score_map.get(ability.id).score, 1) if ability.id in score_map else 0),
            }
            for ability in abilities
        ]
        ability_name_map = {item.key: item.name for item in abilities}

        grouped: defaultdict[tuple[str, str], list[float]] = defaultdict(list)
        for answer, question in answer_rows:
            point = (question.knowledge_point or "综合知识").strip()
            normalized = max(0.0, min(100.0, answer.score / max(1, question.max_score) * 100))
            grouped[(point, question.ability_key or "")].append(normalized)

        mastery_items: list[dict[str, Any]] = []
        for (point, ability_key), values in grouped.items():
            # 越近的作答权重越高，路径会随最新实训结果动态调整。
            weights = [0.85 ** (len(values) - index - 1) for index in range(len(values))]
            score = sum(value * weight for value, weight in zip(values, weights, strict=True)) / sum(weights)
            recent = values[-3:]
            critical = ability_key == "safety_awareness" and any(value < 80 for value in recent)
            if critical:
                score = min(score, 59.0)
            mastery_items.append({
                "knowledge_point": point,
                "ability_key": ability_key,
                "ability_name": ability_name_map.get(ability_key, ability_key or "综合能力"),
                "mastery_score": round(score, 1),
                "attempt_count": len(values),
                "wrong_count": sum(value < 60 for value in values),
                "recent_scores": [round(value, 1) for value in recent],
                "safety_critical": critical,
                "state": self._state(score),
            })
        mastery_items.sort(key=lambda item: (not item["safety_critical"], item["mastery_score"], -item["attempt_count"]))

        tasks = (
            await db.execute(
                select(TrainingTask)
                .where(TrainingTask.status == TaskStatus.published)
                .order_by(TrainingTask.difficulty, TrainingTask.id)
            )
        ).scalars().all()
        steps: list[dict[str, Any]] = []
        for mastery in mastery_items:
            if mastery["mastery_score"] >= 80 or len(steps) >= 8:
                continue
            priority = "必须先修" if mastery["safety_critical"] else "优先补强" if mastery["mastery_score"] < 60 else "巩固提升"
            steps.append({
                "id": f"knowledge-{len(steps) + 1}",
                "step_type": "knowledge_review",
                "title": f"补学：{mastery['knowledge_point']}",
                "reason": f"该知识点当前掌握度 {mastery['mastery_score']}%，最近实训错答 {mastery['wrong_count']} 次。",
                "priority": priority,
                "knowledge_point": mastery["knowledge_point"],
                "target_ability": mastery["ability_key"],
                "difficulty": 1 if mastery["mastery_score"] < 40 else 2,
                "estimated_minutes": 10,
                "route": f"/knowledge?query={mastery['knowledge_point']}",
                "safety_critical": mastery["safety_critical"],
            })
            candidates = [
                task for task in tasks
                if mastery["knowledge_point"] in (task.knowledge_points or [])
                or mastery["ability_key"] in (task.target_abilities or [])
            ]
            if candidates and len(steps) < 8:
                target_difficulty = 1 if mastery["mastery_score"] < 30 else 2 if mastery["mastery_score"] < 60 else 3
                candidates.sort(key=lambda item: (abs(item.difficulty - target_difficulty), item.id))
                task = candidates[0]
                steps.append({
                    "id": f"practice-{len(steps) + 1}",
                    "step_type": "training_retry",
                    "title": f"重练：{task.title}",
                    "reason": f"用于验证「{mastery['knowledge_point']}」补学效果；完成后系统将重新计算掌握度。",
                    "priority": priority,
                    "knowledge_point": mastery["knowledge_point"],
                    "target_ability": mastery["ability_key"],
                    "task_id": task.id,
                    "task_code": task.code,
                    "difficulty": task.difficulty,
                    "estimated_minutes": task.estimated_minutes,
                    "route": f"/training/{task.code}",
                    "safety_critical": mastery["safety_critical"],
                })

        if not answer_rows:
            for task in tasks[:3]:
                steps.append({
                    "id": f"diagnostic-{len(steps) + 1}",
                    "step_type": "diagnostic_training",
                    "title": f"诊断训练：{task.title}",
                    "reason": "尚无已完成实训数据，先通过诊断任务建立个人能力与知识掌握基线。",
                    "priority": "建立基线",
                    "knowledge_point": (task.knowledge_points or ["综合知识"])[0],
                    "target_ability": (task.target_abilities or [""])[0],
                    "task_id": task.id,
                    "task_code": task.code,
                    "difficulty": task.difficulty,
                    "estimated_minutes": task.estimated_minutes,
                    "route": f"/training/{task.code}",
                    "safety_critical": False,
                })

        weak_count = sum(item["mastery_score"] < 60 for item in mastery_items)
        learning_count = sum(60 <= item["mastery_score"] < 80 for item in mastery_items)
        mastered_count = sum(item["mastery_score"] >= 80 for item in mastery_items)
        overall = round(sum(item["mastery_score"] for item in mastery_items) / len(mastery_items), 1) if mastery_items else 0
        return {
            "student_id": student_id,
            "data_boundary": "仅根据该学生的实训选择题明细和个人能力画像生成，不影响专业培养方案。",
            "summary": {
                "overall_mastery": overall,
                "knowledge_count": len(mastery_items),
                "weak_count": weak_count,
                "learning_count": learning_count,
                "mastered_count": mastered_count,
                "completed_answer_count": len(answer_rows),
                "path_step_count": len(steps),
            },
            "ability_state": ability_state,
            "knowledge_mastery": mastery_items,
            "learning_path": steps,
            "next_step": steps[0] if steps else None,
            "refresh_rule": "每次实训完成后实时重算；近期作答权重更高，安全类低分强制优先。",
        }

    @staticmethod
    def _state(score: float) -> str:
        if score >= 80:
            return "mastered"
        if score >= 60:
            return "learning"
        return "weak"


__all__ = ["AdaptiveLearningService"]
