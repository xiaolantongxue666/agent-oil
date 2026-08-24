"""Mock LLM Provider（第三十一节）。

无真实网络调用的确定性兜底实现：
- `llm_use_mock=True` 或缺失 API Key 时启用。
- 保证项目在无密钥环境下仍可端到端运行（竞赛演示/离线评审）。
- 返回内容明确标注为"教学模拟"，不得冒充真实标准/真实生产数据。
"""

from __future__ import annotations

import asyncio
import json
import re
from collections.abc import AsyncIterator
from typing import Any

from app.llm.base import LLMMessage, LLMProvider, LLMResponse

# 所有 Mock 输出统一标注，避免与真实标准/数据混淆
_MOCK_TAG = "【教学模拟】"


def _looks_like_json_request(messages: list[LLMMessage]) -> bool:
    """判断当前对话是否要求返回 JSON。"""
    if _keyword_in(messages, "supported_knowledge_indexes", "supported_business_indexes"):
        return True
    for m in messages:
        if m.role.value == "system" and ("json" in m.content.lower() or "JSON" in m.content):
            return True
    return False


def _keyword_in(messages: list[LLMMessage], *keys: str) -> bool:
    blob = "\n".join(m.content for m in messages)
    return any(k.lower() in blob.lower() for k in keys)


def _structured_template(messages: list[LLMMessage]) -> dict[str, Any]:
    """根据对话关键词返回对应结构化模板（教学模拟数据）。"""
    if _keyword_in(messages, "只读证据核验器", "supported_knowledge_indexes"):
        blob = "\n".join(message.content for message in messages)
        answer_match = re.search(r"<answer>\s*(.*?)\s*</answer>", blob, re.DOTALL)
        answer = answer_match.group(1) if answer_match else ""
        return {
            "supported_knowledge_indexes": sorted(
                {int(value) for value in re.findall(r"\[(\d+)\]", answer)}
            ),
            "supported_business_indexes": sorted(
                {int(value) for value in re.findall(r"\[B(\d+)\]", answer, re.IGNORECASE)}
            ),
        }
    if _keyword_in(messages, "选择题题库", "单项选择题", "question_bank"):
        return {
            "questions": [
                {
                    "stem": f"{_MOCK_TAG}开始岗位实训前，哪项准备更符合教学规范？",
                    "ability_key": "safety_awareness",
                    "knowledge_point": "任务准备与风险确认",
                    "explanation": "应先核对任务、情境条件、风险提示和教学依据。",
                    "options": [
                        {"key": "A", "content": "直接开始，不核对任务条件", "score": 0, "feedback": "缺少必要核对。", "is_correct": False},
                        {"key": "B", "content": "核对任务条件、风险提示和教学依据", "score": 100, "feedback": "判断正确。", "is_correct": True},
                        {"key": "C", "content": "只查看任务标题", "score": 40, "feedback": "信息不完整。", "is_correct": False},
                        {"key": "D", "content": "未经授权操作真实设备验证", "score": 0, "feedback": "不符合教学安全边界。", "is_correct": False},
                    ],
                },
                {
                    "stem": f"{_MOCK_TAG}发现信息与历史记录不一致时，应如何处理？",
                    "ability_key": "abnormal_detection",
                    "knowledge_point": "异常信息核查",
                    "explanation": "应客观记录差异并按教学流程核查报告。",
                    "options": [
                        {"key": "A", "content": "修改数据使其一致", "score": 0, "feedback": "不得修改客观数据。", "is_correct": False},
                        {"key": "B", "content": "忽略差异", "score": 0, "feedback": "异常线索不应忽略。", "is_correct": False},
                        {"key": "C", "content": "记录差异、复核来源并报告", "score": 100, "feedback": "判断正确。", "is_correct": True},
                        {"key": "D", "content": "直接认定设备故障", "score": 40, "feedback": "结论过早。", "is_correct": False},
                    ],
                },
                {
                    "stem": f"{_MOCK_TAG}实训记录怎样填写更便于教师复盘？",
                    "ability_key": "standard_recording",
                    "knowledge_point": "实训记录完整性",
                    "explanation": "记录应包含时间、对象、现象、判断依据、选择结果和待核查项。",
                    "options": [
                        {"key": "A", "content": "只写已完成", "score": 0, "feedback": "记录不可追溯。", "is_correct": False},
                        {"key": "B", "content": "只记录最终得分", "score": 40, "feedback": "缺少过程信息。", "is_correct": False},
                        {"key": "C", "content": "删除错误选择", "score": 0, "feedback": "应保留学习过程。", "is_correct": False},
                        {"key": "D", "content": "完整记录情境、选择、依据、反馈和待复盘点", "score": 100, "feedback": "判断正确。", "is_correct": True},
                    ],
                },
            ],
            "note": _MOCK_TAG,
        }
    if _keyword_in(messages, "教学策略", "teaching_strategy", "strategy"):
        return {
            "strategy": "guided_practice",
            "difficulty": "basic",
            "steps": [
                {"name": "情境导入", "desc": "介绍输气站工艺流程与巡检要点"},
                {"name": "任务下发", "desc": "下发巡检任务单"},
                {"name": "学生作答", "desc": "学生按巡检路线逐项检查"},
                {"name": "评价反馈", "desc": "六维能力评分与追问"},
            ],
            "note": _MOCK_TAG,
        }
    if _keyword_in(messages, "任务生成", "task_generate", "生成任务", "巡检任务"):
        return {
            "title": "输气站日常巡检基础训练",
            "scene": "输气站",
            "checklist": [
                "工艺管线有无渗漏",
                "阀门开闭状态是否正确",
                "仪表参数是否在允许区间",
                "安全附件是否完好",
            ],
            "note": _MOCK_TAG,
        }
    if _keyword_in(messages, "评价", "eval", "rubric", "评分", "维度"):
        return {
            "llm_subscore": 80.0,
            "dimensions": {
                "process_understanding": "理解巡检流程，顺序基本正确。",
                "safety_awareness": "识别出主要风险点，防护意识良好。",
            },
            "comment": _MOCK_TAG + "评价理由：流程理解到位，参数核对略有疏漏。",
            "safety_flag": "normal",
        }
    if _keyword_in(messages, "重写", "rewrite", "改写", "扩展", "query"):
        return {"rewritten_queries": ["输气站巡检要点", "巡检安全注意事项", "工艺参数核对"]}
    if _keyword_in(messages, "解释", "explain", "讲解", "说明"):
        return {
            "explanation": _MOCK_TAG + "巡检应遵循由整体到局部、由上游到下游的顺序。",
            "citations": [],
        }
    if _keyword_in(messages, "推荐", "recommend", "建议", "下一步"):
        return {
            "recommendations": [
                {"type": "training", "task_id": "TT-01", "reason": "强化参数核对能力"},
                {"type": "knowledge", "topic": "阀门维护", "reason": "补强设备识别维度"},
            ],
        }
    # 通用结构化兜底
    return {"note": _MOCK_TAG, "data": "通用教学模拟结构化输出"}


def _plain_reply(messages: list[LLMMessage]) -> str:
    """非结构化对话回复（教学模拟）。"""
    if _keyword_in(messages, "你好", "hello", "在吗", "ping"):
        return _MOCK_TAG + "你好，我是油训智安教学助手（离线演示模式）。"
    blob = "\n".join(message.content for message in messages)
    business_indexes = sorted({int(value) for value in re.findall(r"\[B(\d+)\]", blob)})
    markers = "".join(f"[B{index}]" for index in business_indexes)
    if _keyword_in(messages, "[1] 标题："):
        return _MOCK_TAG + f"已根据本轮实际证据组织回答{markers}，相关结论见资料[1]。"
    if markers:
        return _MOCK_TAG + f"已根据本轮业务功能结果组织回答{markers}。"
    return _MOCK_TAG + "已收到你的问题。在离线演示模式下，此回复为模拟内容，仅供功能演示。"


class MockLLMProvider(LLMProvider):
    """离线确定性 LLM 兜底。"""

    name = "mock"

    def __init__(self, model: str = "mock-qwen", temperature: float = 0.2) -> None:
        self._model = model
        self._temperature = temperature

    async def chat(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        **_kwargs: Any,
    ) -> LLMResponse:
        if _looks_like_json_request(messages):
            template = _structured_template(messages)
            content = "```json\n" + json.dumps(template, ensure_ascii=False, indent=2) + "\n```"
        else:
            content = _plain_reply(messages)
        return LLMResponse(
            content=content,
            model=self._model,
            finish_reason="stop",
            usage={"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0},
            provider=self.name,
        )

    async def health(self) -> bool:
        return True

    async def chat_stream(
        self,
        messages: list[LLMMessage],
        *,
        temperature: float | None = None,
        max_tokens: int | None = None,
        timeout: float | None = None,
        **_kwargs: Any,
    ) -> AsyncIterator[str]:
        """离线演示模式下的模拟流式输出：逐块产出，保留打字机效果。"""
        resp = await self.chat(
            messages, temperature=temperature, max_tokens=max_tokens, timeout=timeout
        )
        content = resp.content
        chunk_size = 4
        for start in range(0, len(content), chunk_size):
            yield content[start : start + chunk_size]
            await asyncio.sleep(0.02)


__all__ = ["MockLLMProvider"]
