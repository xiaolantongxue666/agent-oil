"""知识问答工作流节点（第四十三节 QA 流程）。

流程：intent → input_guard → clarify → query_rewrite → retrieve → answer → output_guard → done
- 输入/输出守卫由代码规则控制，LLM 不参与守卫决策
- LLM 仅用于查询改写与答案生成（语言推理）
- 路由由工作流引擎的条件路由决定，不由 LLM 决定
- 所有检索证据带引用，无来源则不编造
"""

from __future__ import annotations

from typing import Any

from app.core.logging import logger
from app.llm import LLMMessage, get_gateway
from app.rag import (
    format_citation_text,
    get_pipeline,
    strip_model_citation_section,
)
from app.safety import build_safe_output_message, get_safety_guard
from app.services.prompt_templates import get_prompt_messages
from app.workflow.context import WorkflowContext
from app.workflow.enums import WorkflowState
from app.workflow.nodes.base import BaseWorkflowNode

_REFERENCE_PATTERNS = ("这个", "那个", "它", "这里", "刚才那个")
_GENERIC_QUESTIONS = {"怎么弄", "怎么弄？", "怎么办", "怎么办？", "怎么处理", "怎么处理？"}
def _as_untrusted_data(value: str) -> str:
    """Prevent untrusted text from closing prompt boundary tags."""
    return value.replace("<", "＜").replace(">", "＞")


async def _build_answer_messages(
    context: WorkflowContext,
    knowledge_ctx: str,
    question: str,
) -> list[LLMMessage]:
    """组装 QA 答案生成的 LLM 消息列表（流式/非流式共用）。"""
    system_prompt, user_prompt = await get_prompt_messages(
        "qa_answer",
        {
            "knowledge_context": knowledge_ctx,
            "trusted_business_facts": _as_untrusted_data(
                context.metadata.get("controlled_business_facts", "")
            ),
            "question": question,
        },
    )
    boundary_system, _ = await get_prompt_messages("qa_evidence_boundary", {})
    messages = [LLMMessage.system(boundary_system), LLMMessage.system(system_prompt)]
    history = "\n".join(
        f"{message.role}: {_as_untrusted_data(message.content)}"
        for message in context.messages[-8:]
    )
    if history:
        messages.append(
            LLMMessage.user(
                "<untrusted_conversation_history>\n"
                f"{history}\n"
                "</untrusted_conversation_history>"
            )
        )
    messages.append(LLMMessage.user(user_prompt))
    return messages

class IntentNode(BaseWorkflowNode):
    """意图识别：聊天入口固定为 QA 意图。"""

    name = "intent"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        # Preserve deterministic intent supplied by the chat orchestrator.
        if not context.intent or context.intent == "qa":
            context.intent = "knowledge_qa"
        context.mode = "qa"
        context.next_node = "input_guard"
        return context


class InputGuardNode(BaseWorkflowNode):
    """输入安全守卫：拦截控制指令/请求真实数据/敏感信息。"""

    name = "input_guard"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        guard = get_safety_guard()
        result = guard.check_input(context.user_input or "")
        if not result.safe:
            context.metadata["safety_reject"] = {
                "reason": result.reason,
                "category": result.category,
            }
            context.add_message(
                "assistant",
                f"您的输入未通过安全校验：{result.reason}。请调整后重试。",
            )
            context.metadata["answer"] = f"（安全拦截）{result.reason}"
            context.state = WorkflowState.COMPLETED
            context.next_node = None
            logger.info("输入守卫拦截：{} ({})", result.category, context.user_input[:50])
            return context
        context.next_node = "clarify"
        return context


class ClarifyNode(BaseWorkflowNode):
    """对缺少对象的指代问题先澄清，避免带着错误假设检索。"""

    name = "clarify"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        query = (context.user_input or "").strip()
        ambiguous = (
            (len(query) <= 24 and any(pattern in query for pattern in _REFERENCE_PATTERNS))
            or query in _GENERIC_QUESTIONS
        )
        if not ambiguous:
            context.next_node = "query_rewrite"
            return context

        prior_users = [m.content for m in context.messages if m.role == "user" and m.content.strip()]
        topic = prior_users[-1] if prior_users else "当前任务"
        topic = topic[:36] + ("…" if len(topic) > 36 else "")
        answer = (
            f"为了准确回答，请确认你说的“这个”具体指什么。"
            f"是「{topic}」中的设备识别、参数判读、流程步骤，还是安全与记录要求？"
        )
        context.metadata["answer"] = answer
        context.metadata["citations"] = []
        context.metadata["needs_clarification"] = True
        context.add_message("assistant", answer)
        context.state = WorkflowState.COMPLETED
        context.next_node = None
        return context


class QueryRewriteNode(BaseWorkflowNode):
    """查询改写：用 LLM 扩展检索关键词；失败则回退原查询。"""

    name = "query_rewrite"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        query = context.user_input or ""
        prior_users = [m.content for m in context.messages if m.role == "user" and m.content.strip()]
        contextual_query = query
        if prior_users and len(query) <= 30:
            contextual_query = f"上一轮主题：{prior_users[-1]}；当前追问：{query}"
        search_query = query
        try:
            gw = get_gateway()
            boundary_system, _ = await get_prompt_messages("qa_evidence_boundary", {})
            system_prompt, user_prompt = await get_prompt_messages(
                "qa_query_rewrite",
                {
                    "contextual_query": (
                        "<untrusted_query_context>\n"
                        f"{_as_untrusted_data(contextual_query)}\n"
                        "</untrusted_query_context>"
                    )
                },
            )
            result = await gw.chat_structured(
                [
                    LLMMessage.system(boundary_system),
                    LLMMessage.system(system_prompt),
                    LLMMessage.user(user_prompt),
                ],
                schema_description='{"keywords": [str]}',
                temperature=0.1,
            )
            if result.success and result.data:
                kws = result.data.get("keywords", [])
                if isinstance(kws, list) and kws:
                    context.metadata["rewritten_keywords"] = kws
                    search_query = contextual_query + " " + " ".join(str(k) for k in kws)
        except Exception as exc:  # noqa: BLE001
            logger.debug("查询改写失败，回退原查询：{}", exc)
        context.metadata["search_query"] = search_query
        context.next_node = "retrieve"
        return context


class RetrieveNode(BaseWorkflowNode):
    """检索 + 重排：调用 RAG Pipeline，写入 retrieved_documents。"""

    name = "retrieve"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        pipeline = get_pipeline()
        query = context.metadata.get("search_query") or context.user_input or ""
        filters = context.metadata.get("filters")
        try:
            docs = await pipeline.retrieve_and_rerank(query, filters=filters)
        except Exception as exc:  # noqa: BLE001
            logger.warning("检索失败，返回空结果：{}", exc)
            docs = []
        context.retrieved_documents = docs
        logger.info("QA 检索完成：{} 条相关文档", len(docs))
        context.next_node = "answer"
        return context


class AnswerNode(BaseWorkflowNode):
    """答案生成：LLM 基于检索资料生成回答（语言推理）。

    支持流式：若 context.metadata["stream_sink"] 存在（异步队列），
    则在完整消费模型流的同时逐块推送给路由层（SSE），
    输出守卫仍在完整回答上执行。
    """

    name = "answer"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        pipeline = get_pipeline()
        docs = context.retrieved_documents
        citations: list[dict[str, Any]] = []
        # 组装资料上下文
        if docs:
            ctx_parts = []
            for i, d in enumerate(docs, 1):
                citation = pipeline.to_citation(d)
                source = format_citation_text(citation) or "来源元数据：未提供"
                ctx_parts.append(
                    f"[{i}] 标题：{_as_untrusted_data(d.title)}\n"
                    f"{_as_untrusted_data(source)}\n"
                    f"内容：{_as_untrusted_data(d.content)}"
                )
                citations.append(citation)
            knowledge_ctx = "\n\n".join(ctx_parts)
            # 引用卡片按（知识编号+章节）去重：同一文件同章节的多个分块
            # 仍可全部进入检索上下文，但对外只展示一条引用
            deduped: list[dict[str, Any]] = []
            seen: set[tuple[str, str]] = set()
            for citation in citations:
                key = (str(citation.get("knowledge_id", "")), str(citation.get("chapter", "")))
                if key in seen:
                    continue
                seen.add(key)
                deduped.append(citation)
            context.metadata["citations"] = deduped
        else:
            knowledge_ctx = "（无检索资料，请基于通用专业知识谨慎作答并注明无具体来源）"
            context.metadata["citations"] = []

        question = _as_untrusted_data(context.user_input or "")
        messages = await _build_answer_messages(context, knowledge_ctx, question)
        sink = context.metadata.get("stream_sink")
        try:
            gw = get_gateway()
            if sink is not None:
                raw = await self._generate_streaming(gw, messages, sink)
                context.metadata["streamed"] = True
                # 引用信息由前端「引用来源」卡片展示；仅剥离模型自造的依据清单
                answer = strip_model_citation_section(raw)
            else:
                resp = await gw.chat(messages, temperature=0.2)
                answer = strip_model_citation_section(resp.content)
        except Exception as exc:  # noqa: BLE001
            logger.error("答案生成失败：{}", exc)
            answer = "（答案生成服务暂不可用，请稍后重试。当前为教学模拟环境。）"
            if sink is not None:
                await sink.put(answer)
        context.metadata["answer"] = answer
        context.add_message("assistant", answer)
        context.next_node = "output_guard"
        return context

    async def _generate_streaming(self, gw, messages: list[LLMMessage], sink) -> str:
        """完整消费 LLM 流，逐块推送给路由层，返回累计原始文本。"""
        raw_parts: list[str] = []
        async for piece in gw.chat_stream(messages, temperature=0.2):
            if piece:
                raw_parts.append(piece)
                # 有界队列提供背压；客户端较慢时不丢失模型分片。
                await sink.put(piece)
        return "".join(raw_parts)


class OutputGuardNode(BaseWorkflowNode):
    """输出安全守卫：拦截真实控制指令与编造标准编号。"""

    name = "output_guard"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        guard = get_safety_guard()
        answer = context.metadata.get("answer", "")
        result = guard.check_output(answer)
        if not result.safe:
            context.metadata["safety_reject_output"] = {
                "reason": result.reason,
                "category": result.category,
            }
            safe_msg = build_safe_output_message(result)
            context.metadata["answer"] = safe_msg
            # 更新最后一条 assistant 消息
            if context.messages and context.messages[-1].role == "assistant":
                context.messages[-1].content = safe_msg
            context.metadata["citations"] = []
            logger.info("输出守卫拦截：{}", result.category)
        context.next_node = "done"
        return context


class DoneNode(BaseWorkflowNode):
    """终态节点。"""

    name = "done"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.state = WorkflowState.COMPLETED
        context.next_node = None
        return context


def qa_nodes() -> list[BaseWorkflowNode]:
    """返回 QA 工作流全部节点。"""
    return [
        IntentNode(),
        InputGuardNode(),
        ClarifyNode(),
        QueryRewriteNode(),
        RetrieveNode(),
        AnswerNode(),
        OutputGuardNode(),
        DoneNode(),
    ]


def qa_routes(router: Any) -> None:
    """注册 QA 条件路由。"""
    # input_guard → 安全则 query_rewrite，否则 done（已在节点内短路到 COMPLETED）
    router.set_default("input_guard", "clarify")
    router.set_default("intent", "input_guard")
    router.set_default("clarify", "query_rewrite")
    router.set_default("query_rewrite", "retrieve")
    router.set_default("retrieve", "answer")
    router.set_default("answer", "output_guard")
    router.set_default("output_guard", "done")


__all__ = [
    "IntentNode",
    "InputGuardNode",
    "ClarifyNode",
    "QueryRewriteNode",
    "RetrieveNode",
    "AnswerNode",
    "OutputGuardNode",
    "DoneNode",
    "qa_nodes",
    "qa_routes",
]
