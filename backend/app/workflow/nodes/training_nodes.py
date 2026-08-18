"""情境实训工作流节点（第四十三节 Training 流程）。

流程：teaching_strategy → present_scenario → (WAITING_INPUT)
      → student_answer → evaluate → (follow_up or done)
      → follow_up → (WAITING_INPUT) → student_answer → evaluate → ...
      → done

- LLM 仅用于教学策略/情境生成/评价理由/追问——路由由引擎决定
- 混合评分（Rule+Semantic+LLM）由 PHASE 8 完善；此处仅做 LLM 子评分
- 能力画像更新由 PHASE 9 的 ProfileUpdateNode 负责
- 推荐由 PHASE 10 的 RecommendNode 负责
"""

from __future__ import annotations

import json
from typing import Any

from app.core.logging import logger
from app.llm import LLMMessage, get_gateway
from app.safety import get_safety_guard
from app.services.prompt_templates import get_prompt_messages
from app.workflow.context import WorkflowContext
from app.workflow.enums import WorkflowState
from app.workflow.nodes.base import BaseWorkflowNode


# ---------- 教学策略 ----------
class TeachingStrategyNode(BaseWorkflowNode):
    """确定教学策略（引导式/探究式/示范式）。"""

    name = "teaching_strategy"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        strategy = "guided_practice"  # 默认策略
        try:
            gw = get_gateway()
            task_meta = context.metadata.get("task_meta", {})
            system_prompt, user_prompt = await get_prompt_messages(
                "training_strategy",
                {
                    "task_title": task_meta.get("title", "油气储运实训"),
                    "difficulty": task_meta.get("difficulty", 2),
                },
            )
            result = await gw.chat_structured(
                [
                    LLMMessage.system(system_prompt),
                    LLMMessage.user(user_prompt),
                ],
                schema_description='{"strategy":str,"difficulty_hint":str,"teaching_tip":str}',
                temperature=0.2,
            )
            if result.success and result.data:
                strategy = result.data.get("strategy", strategy)
                context.metadata["teaching_tip"] = result.data.get("teaching_tip", "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("教学策略 LLM 调用失败，使用默认策略：{}", exc)
        context.metadata["teaching_strategy"] = strategy
        context.next_node = "present_scenario"
        return context


# ---------- 呈现情境 ----------
class PresentScenarioNode(BaseWorkflowNode):
    """向学生呈现教学情境，等待学生首次作答。"""

    name = "present_scenario"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        scenario = context.metadata.get("scenario", {})
        title = context.metadata.get("task_meta", {}).get("title", "实训任务")
        scenario_text = scenario.get("scenario_text", "")
        if not scenario_text:
            # 生成简短情境（Mock 兜底）
            try:
                gw = get_gateway()
                system_prompt, user_prompt = await get_prompt_messages(
                    "training_scenario",
                    {"task_title": title},
                )
                resp = await gw.chat_structured(
                    [
                        LLMMessage.system(system_prompt),
                        LLMMessage.user(user_prompt),
                    ],
                    schema_description='{"scenario_text":str}',
                )
                if resp.success and resp.data:
                    scenario_text = resp.data.get("scenario_text", "")
            except Exception:  # noqa: BLE001
                pass
        if not scenario_text:
            scenario_text = f"【教学模拟】欢迎来到 [{title}] 实训。请根据专业知识回答以下问题。"

        question = scenario.get("initial_question") or "请结合情境说明你的判断、步骤和安全注意事项。"
        context.metadata["scenario_text"] = scenario_text
        context.metadata["current_coach_question"] = question
        context.add_message("assistant", f"📋 实训情境\n\n{scenario_text}")
        context.add_message("assistant", question)
        context.state = WorkflowState.WAITING_INPUT
        context.next_node = "student_answer"
        return context


# ---------- 学生作答 ----------
class StudentAnswerNode(BaseWorkflowNode):
    """接收学生作答（首次或追问后的作答）。"""

    name = "student_answer"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        answer = context.student_answer or ""
        if not answer:
            # 无作答，继续等待
            context.state = WorkflowState.WAITING_INPUT
            context.next_node = "student_answer"
            return context

        # 安全守卫（输入侧）
        guard = get_safety_guard()
        sr = guard.check_input(answer)
        if not sr.safe:
            context.add_message("assistant", f"（安全拦截）{sr.reason}")
            context.state = WorkflowState.WAITING_INPUT
            context.next_node = "student_answer"
            context.student_answer = ""  # 清空，等待重新作答
            return context

        # 记录作答
        context.attempt_count += 1
        round_num = context.attempt_count
        is_follow_up = round_num > 1
        answers = context.metadata.get("answers", [])
        answers.append({
            "round": round_num,
            "content": answer,
            "is_follow_up": is_follow_up,
        })
        context.metadata["answers"] = answers
        logger.info("学生作答 轮次={} 长度={}", round_num, len(answer))
        context.next_node = "evaluate"
        return context


# ---------- 评价 ----------
class EvaluateNode(BaseWorkflowNode):
    """混合评价节点（PHASE 8：Rule + Semantic + LLM → Final）。"""

    name = "evaluate"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        answer = context.student_answer or ""
        task_meta = context.metadata.get("task_meta", {})
        required = task_meta.get("required_points", [])
        reference = task_meta.get("reference_points", [])
        authority_evidence = context.metadata.get("authority_evidence", [])
        evidence_text = "\n".join(
            f"- [{item.get('source_no', '')}，PDF第{item.get('page', '-')}页] {item.get('content', '')}"
            for item in authority_evidence[:8]
        )

        # 决策：是否需要追问
        max_fu = context.max_follow_ups
        need_follow_up = context.follow_up_count < max_fu and context.attempt_count <= max_fu

        if need_follow_up:
            # 中间轮次：轻量 LLM 评价（用于追问生成）
            llm_result = {"llm_subscore": 70.0, "dimensions": {}, "comment": "教学模拟默认评分"}
            try:
                gw = get_gateway()
                system_prompt, user_prompt = await get_prompt_messages(
                    "training_intermediate_evaluation",
                    {
                        "task_title": task_meta.get("title", "实训"),
                        "required_points": json.dumps(required, ensure_ascii=False),
                        "reference_points": json.dumps(reference, ensure_ascii=False),
                        "authority_evidence": evidence_text,
                        "answer": answer,
                    },
                )
                resp = await gw.chat_structured(
                    [
                        LLMMessage.system(system_prompt),
                        LLMMessage.user(user_prompt),
                    ],
                    schema_description='{"llm_subscore":float,"dimensions":{},"comment":str,"safety_flag":str}',
                    temperature=0.1,
                )
                if resp.success and resp.data:
                    llm_result = resp.data
            except Exception as exc:  # noqa: BLE001
                logger.debug("评价 LLM 失败：{}", exc)
            context.metadata["llm_eval"] = llm_result
            raw = llm_result.get("llm_subscore", 70)
            if raw is None:
                raw = 70
            context.metadata["current_llm_score"] = float(raw)
        else:
            # 最终轮次：完整混合评价流水线
            try:
                from app.evaluation import EvaluationInput, EvaluationPipeline

                pipeline = EvaluationPipeline()
                inp = EvaluationInput(
                    answer=answer,
                    task_title=task_meta.get("title", ""),
                    required_points=required or [],
                    reference_points=reference or [],
                    authority_evidence=authority_evidence,
                )
                eval_output = await pipeline.evaluate(inp)
                context.metadata["final_eval"] = eval_output.to_metadata()
                context.metadata["current_llm_score"] = eval_output.llm_score
                context.score = eval_output.final_score
                logger.info(
                    "混合评价完成：rule={:.0f} semantic={:.0f} llm={:.0f} final={:.0f}",
                    eval_output.rule_score,
                    eval_output.semantic_score,
                    eval_output.llm_score,
                    eval_output.final_score,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("混合评价失败，降级为 LLM 评分：{}", exc)
                context.metadata["current_llm_score"] = 70.0

        context.next_node = "follow_up" if need_follow_up else "training_done"
        return context


# ---------- 追问 ----------
class FollowUpNode(BaseWorkflowNode):
    """苏格拉底式追问：基于学生作答薄弱点生成追问。"""

    name = "follow_up"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.follow_up_count += 1
        if context.follow_up_count > context.max_follow_ups:
            context.next_node = "training_done"
            return context

        # 生成追问
        question = ""
        try:
            gw = get_gateway()
            last_answer = context.student_answer or ""
            eval_data = context.metadata.get("llm_eval", {})
            authority_evidence = context.metadata.get("authority_evidence", [])
            evidence_text = "\n".join(
                f"- [{item.get('source_no', '')}，PDF第{item.get('page', '-')}页] {item.get('content', '')}"
                for item in authority_evidence[:4]
            )
            system_prompt, user_prompt = await get_prompt_messages(
                "training_follow_up",
                {
                    "answer": last_answer[:200],
                    "evaluation": json.dumps(eval_data, ensure_ascii=False)[:300],
                    "authority_evidence": evidence_text,
                },
            )
            resp = await gw.chat_structured(
                [
                    LLMMessage.system(system_prompt),
                    LLMMessage.user(user_prompt),
                ],
                schema_description='{"follow_up_question":str}',
            )
            if resp.success and resp.data:
                question = resp.data.get("follow_up_question", "")
        except Exception as exc:  # noqa: BLE001
            logger.debug("追问 LLM 失败：{}", exc)
        if not question:
            question = f"【教学模拟】追问第 {context.follow_up_count} 次：请进一步说明你在巡检中如何确认参数异常？"

        # 输出守卫：检查 LLM 生成的追问内容
        guard = get_safety_guard()
        output_check = guard.check_output(question)
        if not output_check.safe:
            logger.warning("追问输出被安全守卫拦截：{}", output_check.reason)
            question = f"【教学模拟】追问第 {context.follow_up_count} 次：请补充更多关于安全操作规程的细节。"

        context.add_message("assistant", f"🔄 追问 {context.follow_up_count}/{context.max_follow_ups}\n\n{question}")
        context.metadata["current_coach_question"] = question
        context.student_answer = ""  # 清空，等待下一轮作答
        context.state = WorkflowState.WAITING_INPUT
        context.next_node = "student_answer"
        return context


# ---------- 完成 ----------
class TrainingDoneNode(BaseWorkflowNode):
    """实训完成：汇总评分，输出最终结果。"""

    name = "training_done"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        # 最终得分：优先使用混合评价结果（PHASE 8），否则用 LLM 子评分
        final_eval = context.metadata.get("final_eval")
        if final_eval and final_eval.get("final_score"):
            context.score = float(final_eval["final_score"])
        else:
            llm_score = context.metadata.get("current_llm_score") or 70.0
            context.score = float(llm_score)
            context.metadata["final_eval"] = {
                "final_score": context.score,
                "rule_score": 0,
                "semantic_score": 0,
                "llm_score": context.score,
                "explanation": context.metadata.get("llm_eval", {}).get("comment", ""),
                "citations": context.metadata.get("evidence_citations", []),
            }
        context.state = WorkflowState.COMPLETED
        context.next_node = None
        logger.info("实训完成：score={}", context.score)
        return context


def training_nodes() -> list[BaseWorkflowNode]:
    """返回实训工作流全部节点。"""
    return [
        TeachingStrategyNode(),
        PresentScenarioNode(),
        StudentAnswerNode(),
        EvaluateNode(),
        FollowUpNode(),
        TrainingDoneNode(),
    ]


def training_routes(router: Any) -> None:
    """注册实训条件路由默认值。"""
    router.set_default("teaching_strategy", "present_scenario")
    router.set_default("student_answer", "evaluate")
    router.set_default("evaluate", "training_done")  # 节点内部会覆盖
    router.set_default("follow_up", "student_answer")


__all__ = [
    "TeachingStrategyNode",
    "PresentScenarioNode",
    "StudentAnswerNode",
    "EvaluateNode",
    "FollowUpNode",
    "TrainingDoneNode",
    "training_nodes",
    "training_routes",
]
