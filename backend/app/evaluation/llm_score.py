"""LLM 评分器（LLMScore）。

LLM 仅评价：
- 推理过程质量
- 原因解释清晰度
- 表达质量
- 完整性
- 是否形成岗位思维

LLM Score 不能直接成为 Final Score——仅作为子评分参与加权。
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from app.core.logging import logger
from app.llm import LLMMessage, get_gateway
from app.services.prompt_templates import get_definition, get_prompt_messages, render_prompt


@dataclass
class LLMScoreResult:
    """LLM 评分结果。"""

    score: float = 0.0  # 0-100
    dimensions: dict[str, float] = field(default_factory=dict)
    comment: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class LLMScore:
    """基于 LLM 的推理质量评分器。"""

    async def score(
        self,
        answer: str,
        task_title: str = "",
        required_points: list[str] | None = None,
        reference_points: list[str] | None = None,
        authority_evidence: list[dict[str, Any]] | None = None,
    ) -> LLMScoreResult:
        """调用 LLM 评价学生作答的推理质量。"""
        result = LLMScoreResult()

        try:
            gw = get_gateway()
            variables = self._prompt_variables(
                answer,
                task_title,
                required_points,
                reference_points,
                authority_evidence,
            )
            system_prompt, prompt = await get_prompt_messages("evaluation_final", variables)
            resp = await gw.chat_structured(
                [
                    LLMMessage.system(system_prompt),
                    LLMMessage.user(prompt),
                ],
                schema_description=(
                    '{"score":float,"dimensions":{"reasoning":float,"explanation":float,'
                    '"expression":float,"completeness":float,"professional_thinking":float},'
                    '"comment":str}'
                ),
                temperature=0.1,
            )
            if resp.success and resp.data:
                data = resp.data
                result.score = float(data.get("score", 70))
                result.dimensions = {
                    k: float(v)
                    for k, v in (data.get("dimensions") or {}).items()
                    if isinstance(v, (int, float))
                }
                result.comment = data.get("comment", "")
                result.details = {"llm_response": True}
            else:
                result.score = 70.0
                result.comment = "【教学模拟】LLM 未返回有效评价，使用默认评分"
                result.details = {"llm_response": False}
        except Exception as exc:  # noqa: BLE001
            logger.debug("LLM 评分失败：{}", exc)
            result.score = 70.0
            result.comment = f"【教学模拟】LLM 评分降级：{exc}"
            result.details = {"error": str(exc), "fallback": True}

        return result

    def _build_prompt(
        self,
        answer: str,
        task_title: str,
        required_points: list[str] | None,
        reference_points: list[str] | None,
        authority_evidence: list[dict[str, Any]] | None = None,
    ) -> str:
        definition = get_definition("evaluation_final")
        return render_prompt(
            definition.user_prompt_template,
            self._prompt_variables(
                answer,
                task_title,
                required_points,
                reference_points,
                authority_evidence,
            ),
        )

    @staticmethod
    def _prompt_variables(
        answer: str,
        task_title: str,
        required_points: list[str] | None,
        reference_points: list[str] | None,
        authority_evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, str]:
        evidence_lines = [
            f"[{item.get('source_no', '')}，{item.get('chapter', '')}，PDF第{item.get('page', '-')}页] "
            f"{item.get('content', '')}"
            for item in (authority_evidence or [])[:8]
        ]
        return {
            "task_title": task_title,
            "required_points": json.dumps(required_points or [], ensure_ascii=False),
            "reference_points": json.dumps(reference_points or [], ensure_ascii=False),
            "authority_evidence": "\n".join(evidence_lines),
            "answer": answer[:800],
        }


__all__ = ["LLMScore", "LLMScoreResult"]
