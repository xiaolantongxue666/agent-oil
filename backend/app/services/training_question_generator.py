"""基于任务与权威知识证据生成可审核的选择题草稿。"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel, Field, ValidationError

from app.core.enums import AbilityKey
from app.core.logging import logger
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


_TRUTHY = {"true", "1", "yes", "y", "正确", "是"}
_OPTION_KEYS = ("A", "B", "C", "D")

# 规则模板兜底的轮换素材：避免整批题目逐字相同
_FALLBACK_DISTRACTORS = (
    "只依据个人经验快速判断，不复核任务材料与教学依据。",
    "忽略异常线索，直接按任务已完成提交。",
    "未经授权对真实设备进行操作验证。",
    "仅凭记忆作答，不核对当前任务条件。",
    "先主观下结论，再挑选支持该结论的数据。",
    "跳过风险确认环节，尽快完成操作步骤。",
    "将异常情况搁置，待实训结束后再口头说明。",
    "照抄其他小组的记录结果，不做独立判断。",
)
_FALLBACK_STEMS = (
    "在“{title}”教学情境中，关于“{point}”的判断哪项更规范？",
    "在“{title}”实训任务中，处理“{point}”相关问题时，下列做法哪项符合教学规范？",
    "关于“{title}”任务中的“{point}”，以下哪种处理方式更符合岗位教学要求？",
    "在“{point}”环节，哪项做法最符合“{title}”任务的教学要求？",
)
_FALLBACK_CORRECT_TEMPLATES = (
    "{correct}，并同步记录与复核。",
    "先核对任务条件，再执行：{correct}",
    "规范做法：{correct}",
    "{correct}（依据教学依据逐项确认）",
)


def _as_bool(value: Any) -> bool:
    """健壮布尔解析：模型常把布尔输出成 "true"/"false" 字符串，bool("false") 应为 False。"""
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in _TRUTHY


def _as_score(value: Any) -> int:
    """健壮分数解析：兼容 int/float/"100"/"85分"，非法值记 0，结果夹在 0-100。"""
    try:
        return min(max(int(float(str(value).strip().rstrip("分分"))), 0), 100)
    except (TypeError, ValueError):
        return 0


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
        # 输出预算与超时按题量缩放：每题完整 JSON（题干+解析+4 选项反馈）约需
        # 数百至上千 token，固定 6000 token 会让大批次（如 10 题）被截断、
        # 90s 超时不足，重试耗尽后整批退化为模板题。
        max_tokens = min(16000, 2000 * count + 1000)
        timeout = min(300.0, 60.0 + 24.0 * count)
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
            max_tokens=max_tokens,
            timeout=timeout,
            # 题库草稿是确定性结构化任务，关闭 qwen3 思考模式，
            # 避免思考 token 挤占输出预算并成倍拉高延迟。
            extra_body={"enable_thinking": False},
        )

        valid: list[DraftQuestion] = []
        rejected: list[str] = []
        if structured.success and structured.data:
            raw_questions = structured.data.get("questions") or structured.data.get("items") or []
            for position, raw in enumerate(raw_questions[:count], 1):
                try:
                    valid.append(self._normalise_question(raw, task, len(valid)))
                except (ValidationError, ValueError, TypeError) as exc:
                    reason = str(exc).splitlines()[0][:200]
                    rejected.append(f"第{position}题：{reason}")
                    logger.warning("题库草稿第 {} 题结构校验未通过，已丢弃：{}", position, reason)
        if rejected:
            logger.warning(
                "题库生成结构校验失败 {} 题（成功 {} 题，批次要求 {} 题），失败原因：{}",
                len(rejected), len(valid), count, "；".join(rejected),
            )

        ai_count = len(valid)
        used_fallback = ai_count < count
        if used_fallback:
            fallbacks = self._fallback_questions(task, evidence, count, difficulty, focus_points or [])
            valid.extend(fallbacks[ai_count:count])
        if not used_fallback:
            warning = ""
        elif ai_count == 0:
            warning = "模型输出解析失败或全部未通过结构校验，本批已由规则模板补齐，请教师重点审核。"
        else:
            warning = (
                f"模型仅 {ai_count}/{count} 题通过结构校验，"
                "其余已由规则模板补齐，请教师重点审核。"
            )
        return QuestionGenerationResult(
            questions=valid[:count],
            provider=structured.provider or gateway.provider_name,
            used_fallback=used_fallback,
            attempts=structured.attempts,
            warning=warning,
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

        # ===== 兼容字段别名 =====
        # 题干：优先 stem，回退 question / 题干（模型常用别名）
        stem = str(
            raw.get("stem") or raw.get("question") or raw.get("题干") or ""
        ).strip()
        if not stem:
            raise ValueError("stem/question field is empty")

        # ===== 兼容 options 容器：list 或 dict =====
        options_raw = (
            raw.get("options") or raw.get("choices") or raw.get("选项") or raw.get("option_list")
        )
        if isinstance(options_raw, dict):
            # {"A": {...}} 按键排序转 list；{"A": "文本"} 字符串值也兼容
            options_raw = [
                {"key": str(k), **v} if isinstance(v, dict) else {"key": str(k), "content": v}
                for k, v in sorted(options_raw.items())
            ]
        if not isinstance(options_raw, list) or not 3 <= len(options_raw) <= 5:
            raise ValueError("options must contain 3-5 items")

        options: list[dict[str, Any]] = []
        for option_index, item in enumerate(options_raw):
            if isinstance(item, str):
                item = {"content": item}
            if not isinstance(item, dict):
                raise ValueError("invalid option")
            # 选项文本：content / text / option / option_content 均兼容
            option_content = str(
                item.get("content")
                or item.get("text")
                or item.get("option")
                or item.get("option_content")
                or ""
            ).strip()
            if not option_content:
                raise ValueError("invalid option")
            options.append(
                {
                    "key": str(item.get("key") or _OPTION_KEYS[option_index]).strip().upper()[:8],
                    "content": option_content,
                    "score": _as_score(item.get("score")),
                    "feedback": str(item.get("feedback") or item.get("解析") or "").strip(),
                    "is_correct": _as_bool(
                        item.get("is_correct")
                        if "is_correct" in item
                        else item.get("correct")
                    ),
                }
            )

        # ===== 归一到恰好 4 个选项 =====
        if len(options) > 4:
            correct = [item for item in options if item["is_correct"]]
            others = [item for item in options if not item["is_correct"]]
            options = (correct[:1] + others)[:4]
            options.sort(key=lambda item: item["key"])
            options = [
                {**item, "key": _OPTION_KEYS[i]} for i, item in enumerate(options)
            ]
        elif len(options) == 3:
            used = {item["content"] for item in options}
            extra = next(
                (
                    text
                    for text in _FALLBACK_DISTRACTORS
                    if text not in used
                ),
                "以上处理均不符合教学规范，需教师复核。",
            )
            options.append(
                {
                    "key": "D",
                    "content": extra,
                    "score": 0,
                    "feedback": "",
                    "is_correct": False,
                }
            )

        # ===== 确定唯一正确项 =====
        # 兼容题级答案别名：answer / correct_answer / answer_key / correct_key
        answer_hint = str(
            raw.get("answer")
            or raw.get("correct_answer")
            or raw.get("answer_key")
            or raw.get("correct_key")
            or ""
        ).strip()
        if not any(item["is_correct"] for item in options) and answer_hint:
            hint = answer_hint.upper()
            matched: list[int] = []
            if hint in _OPTION_KEYS:
                matched = [i for i, item in enumerate(options) if item["key"] == hint]
            elif hint in {"1", "2", "3", "4"}:
                matched = [int(hint) - 1]
            else:
                matched = [
                    i for i, item in enumerate(options) if item["content"] == answer_hint
                ]
            if len(matched) == 1:
                options[matched[0]]["is_correct"] = True

        correct_indexes = [i for i, item in enumerate(options) if item["is_correct"]]
        if not correct_indexes:
            highest = max(range(4), key=lambda i: options[i]["score"])
            correct_indexes = [highest]
        correct_index = correct_indexes[0]
        for option_index, item in enumerate(options):
            item["is_correct"] = option_index == correct_index
            item["score"] = 100 if option_index == correct_index else min(item["score"], 80)
            item["key"] = _OPTION_KEYS[option_index]
            if not item["feedback"]:
                item["feedback"] = "判断正确，请结合权威依据理解。" if item["is_correct"] else "该选项不够规范，请复盘知识解析。"

        # ===== 选项内容必须互不相同，否则无作答意义 =====
        contents = [item["content"] for item in options]
        if len(set(contents)) != 4:
            raise ValueError("duplicate option content")

        allowed_abilities = {ability.value for ability in AbilityKey}
        task_abilities = [str(item) for item in (task.target_abilities or []) if str(item) in allowed_abilities]
        ability_key = str(raw.get("ability_key") or "")
        if ability_key not in allowed_abilities:
            ability_key = task_abilities[index % len(task_abilities)] if task_abilities else AbilityKey.safety_awareness.value
        return DraftQuestion.model_validate(
            {
                # 超长字段按上限截断修复，避免整题丢弃
                "stem": stem[:2000],
                "ability_key": ability_key,
                "knowledge_point": (str(raw.get("knowledge_point") or "岗位规范判断").strip())[:128],
                "explanation": (
                    str(raw.get("explanation") or "请依据任务知识和权威教学资料判断。").strip()
                )[:3000],
                "options": [
                    {
                        **item,
                        "content": item["content"][:1000],
                        "feedback": item["feedback"][:2000],
                    }
                    for item in options
                ],
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
            reference = references[index % len(references)] if references else "先核对任务条件和教学依据，客观记录并按教学流程报告。"
            # 正确项做轻量改写，避免与任务“参考要点”原文逐字相同
            correct = _FALLBACK_CORRECT_TEMPLATES[index % len(_FALLBACK_CORRECT_TEMPLATES)].format(
                correct=self._truncate(reference, 400)
            )
            # 干扰项按题轮换取材，避免整批题目选项逐字相同
            choices = [
                _FALLBACK_DISTRACTORS[(index * 3 + offset) % len(_FALLBACK_DISTRACTORS)]
                for offset in range(3)
            ]
            choices = [item for item in choices if item != correct][:3]
            correct_index = (index + difficulty) % 4
            choices.insert(correct_index, correct)
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
            stem_template = _FALLBACK_STEMS[index % len(_FALLBACK_STEMS)]
            questions.append(
                DraftQuestion(
                    stem=stem_template.format(
                        title=self._truncate(task.title, 100),
                        point=self._truncate(point, 60),
                    ),
                    ability_key=abilities[index % len(abilities)],
                    knowledge_point=point,
                    explanation=f"本题依据任务“{task.title}”及其关联知识证据生成，发布前须由教师审核。",
                    options=options,
                )
            )
        return questions

    @staticmethod
    def _truncate(text: str, limit: int) -> str:
        cleaned = str(text or "").strip()
        return cleaned if len(cleaned) <= limit else f"{cleaned[:limit]}…"


__all__ = [
    "DraftOption",
    "DraftQuestion",
    "QuestionGenerationResult",
    "TrainingQuestionGenerator",
]
