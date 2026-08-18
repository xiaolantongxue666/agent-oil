"""基于任务与权威知识证据生成可审核的选择题草稿。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.enums import AbilityKey
from app.llm import LLMMessage, get_gateway
from app.models.training import TrainingTask
from app.services.prompt_templates import get_prompt_messages


class DraftOption(BaseModel):
    key: str = Field(min_length=1, max_length=8)
    content: str = Field(min_length=1, max_length=1000)
    score: int = Field(ge=0, le=100)
    feedback: str = Field(default="", max_length=2000)
    is_correct: bool = False


class DraftQuestion(BaseModel):
    stem: str = Field(min_length=5, max_length=2000)
    ability_key: str = Field(default="", max_length=64)
    knowledge_point: str = Field(default="", max_length=128)
    explanation: str = Field(min_length=5, max_length=3000)
    options: list[DraftOption]


@dataclass
class QuestionGenerationResult:
    questions: list[DraftQuestion]
    provider: str
    used_fallback: bool
    attempts: int
    warning: str = ""


class TrainingQuestionGenerator:
    """LLM 只生成草稿，结构校验与最终持久化由业务代码完成。"""

    async def generate(
        self,
        task: TrainingTask,
        evidence: list[dict[str, Any]],
        *,
        count: int,
        difficulty: int,
        focus_points: list[str] | None = None,
    ) -> QuestionGenerationResult:
        gateway = get_gateway()
        variables = self._prompt_variables(task, evidence, count, difficulty, focus_points or [])
        system_prompt, prompt = await get_prompt_messages("question_generation", variables)
        structured = await gateway.chat_structured(
            [
                LLMMessage.system(system_prompt),
                LLMMessage.user(prompt),
            ],
            schema_description=(
                '{"questions":[{"stem":"题干","ability_key":"六维能力key",'
                '"knowledge_point":"知识点","explanation":"解析",'
                '"options":[{"key":"A","content":"选项",'
                '"score":0,"feedback":"反馈","is_correct":false}]}]}'
            ),
            temperature=0.25,
            max_tokens=6000,
            timeout=90,
        )

        valid: list[DraftQuestion] = []
        if structured.success and structured.data:
            raw_questions = structured.data.get("questions") or structured.data.get("items") or []
            for raw in raw_questions[:count]:
                try:
                    valid.append(self._normalise_question(raw, task, len(valid)))
                except (ValidationError, ValueError, TypeError):
                    continue

        used_fallback = len(valid) < count
        if used_fallback:
            fallbacks = self._fallback_questions(task, evidence, count, difficulty, focus_points or [])
            valid.extend(fallbacks[len(valid):count])
        return QuestionGenerationResult(
            questions=valid[:count],
            provider=structured.provider or gateway.provider_name,
            used_fallback=used_fallback,
            attempts=structured.attempts,
            warning=(
                "模型输出不足或结构校验未通过，缺少部分已使用规则模板补齐，请教师重点审核。"
                if used_fallback
                else ""
            ),
        )

    def generate_offline(
        self,
        task: TrainingTask,
        evidence: list[dict[str, Any]],
        *,
        count: int,
        difficulty: int,
        focus_points: list[str] | None = None,
    ) -> QuestionGenerationResult:
        """不调用外部模型的安全规则模板模式。"""
        return QuestionGenerationResult(
            questions=self._fallback_questions(
                task, evidence, count, difficulty, focus_points or []
            ),
            provider="local-rule-template",
            used_fallback=True,
            attempts=0,
            warning="本批题目由本地规则模板生成，未向外部模型发送数据，请教师结合权威依据重点审核。",
        )

    @staticmethod
    def _normalise_question(raw: Any, task: TrainingTask, index: int) -> DraftQuestion:
        if not isinstance(raw, dict):
            raise ValueError("question must be object")
        options_raw = raw.get("options")
        if not isinstance(options_raw, list) or len(options_raw) != 4:
            raise ValueError("exactly four options required")

        keys = ("A", "B", "C", "D")
        options: list[dict[str, Any]] = []
        for option_index, item in enumerate(options_raw):
            if not isinstance(item, dict) or not str(item.get("content") or "").strip():
                raise ValueError("invalid option")
            options.append(
                {
                    "key": keys[option_index],
                    "content": str(item["content"]).strip(),
                    "score": min(max(int(item.get("score") or 0), 0), 100),
                    "feedback": str(item.get("feedback") or "").strip(),
                    "is_correct": bool(item.get("is_correct")),
                }
            )

        correct_indexes = [i for i, item in enumerate(options) if item["is_correct"]]
        if not correct_indexes:
            highest = max(range(4), key=lambda i: options[i]["score"])
            correct_indexes = [highest]
        correct_index = correct_indexes[0]
        for option_index, item in enumerate(options):
            item["is_correct"] = option_index == correct_index
            item["score"] = 100 if option_index == correct_index else min(item["score"], 80)
            if not item["feedback"]:
                item["feedback"] = "判断正确，请结合权威依据理解。" if item["is_correct"] else "该选项不够规范，请复盘知识解析。"

        allowed_abilities = {ability.value for ability in AbilityKey}
        task_abilities = [str(item) for item in (task.target_abilities or []) if str(item) in allowed_abilities]
        ability_key = str(raw.get("ability_key") or "")
        if ability_key not in allowed_abilities:
            ability_key = task_abilities[index % len(task_abilities)] if task_abilities else AbilityKey.safety_awareness.value
        return DraftQuestion.model_validate(
            {
                "stem": str(raw.get("stem") or "").strip(),
                "ability_key": ability_key,
                "knowledge_point": str(raw.get("knowledge_point") or "岗位规范判断").strip(),
                "explanation": str(raw.get("explanation") or "请依据任务知识和权威教学资料判断。").strip(),
                "options": options,
            }
        )

    @staticmethod
    def _prompt_variables(
        task: TrainingTask,
        evidence: list[dict[str, Any]],
        count: int,
        difficulty: int,
        focus_points: list[str],
    ) -> dict[str, Any]:
        evidence_text = "\n".join(
            f"[{index}] {item.get('title')}｜{item.get('source_no')}｜{item.get('chapter')}｜"
            f"PDF第{item.get('page')}页｜摘要：{str(item.get('content') or '')[:500]}"
            for index, item in enumerate(evidence, 1)
        )
        return {
            "count": count,
            "difficulty": difficulty,
            "task_code": task.code,
            "task_title": task.title,
            "task_description": task.description,
            "scenario": (task.scenario or {}).get("scenario_text", ""),
            "target_abilities": task.target_abilities or [],
            "knowledge_points": focus_points or task.knowledge_points or task.required_points or [],
            "required_points": task.required_points or [],
            "authority_evidence": (
                evidence_text
                or "暂无权威证据，仅依据任务元数据生成并明确待教师审核。"
            ),
        }

    def _fallback_questions(
        self,
        task: TrainingTask,
        evidence: list[dict[str, Any]],
        count: int,
        difficulty: int,
        focus_points: list[str],
    ) -> list[DraftQuestion]:
        points = [str(item) for item in focus_points or task.required_points or task.knowledge_points or []]
        points.extend(str(item.get("knowledge_point") or "") for item in evidence)
        points = list(dict.fromkeys(item for item in points if item)) or ["岗位规范判断"]
        references = [str(item) for item in (task.reference_points or []) if item]
        abilities = [str(item) for item in (task.target_abilities or []) if item]
        if not abilities:
            abilities = [AbilityKey.safety_awareness.value]

        questions: list[DraftQuestion] = []
        for index in range(count):
            point = points[index % len(points)]
            correct = references[index % len(references)] if references else "先核对任务条件和教学依据，客观记录并按教学流程报告。"
            choices = [
                "只依据个人经验快速判断，不再复核材料。",
                correct,
                "忽略异常线索，只填写任务已完成。",
                "未经授权直接进行真实设备操作验证。",
            ]
            correct_index = (index + difficulty) % 4
            correct_content = choices.pop(1)
            choices.insert(correct_index, correct_content)
            options = []
            for option_index, content in enumerate(choices):
                is_correct = option_index == correct_index
                options.append(
                    DraftOption(
                        key=chr(ord("A") + option_index),
                        content=content,
                        score=100 if is_correct else 0,
                        feedback=(
                            f"判断正确，应围绕“{point}”核对任务条件与教学依据。"
                            if is_correct
                            else f"该选项不符合“{point}”的教学规范，请结合任务依据复盘。"
                        ),
                        is_correct=is_correct,
                    )
                )
            questions.append(
                DraftQuestion(
                    stem=f"在“{task.title}”教学情境中，关于“{point}”的判断哪项更规范？",
                    ability_key=abilities[index % len(abilities)],
                    knowledge_point=point,
                    explanation=f"本题依据任务“{task.title}”及其关联知识证据生成，发布前须由教师审核。",
                    options=options,
                )
            )
        return questions


__all__ = [
    "DraftOption",
    "DraftQuestion",
    "QuestionGenerationResult",
    "TrainingQuestionGenerator",
]
