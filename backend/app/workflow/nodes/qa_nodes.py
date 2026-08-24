"""知识问答工作流节点（第四十三节 QA 流程）。

流程：intent → input_guard → clarify → query_rewrite → retrieve → answer → output_guard → done
- 输入/输出守卫由代码规则控制，LLM 不参与守卫决策
- LLM 仅用于查询改写与答案生成（语言推理）
- 路由由工作流引擎的条件路由决定，不由 LLM 决定
- 所有检索证据带引用，无来源则不编造
"""

from __future__ import annotations

import re
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
_INLINE_CITATION_RE = re.compile(r"\[(\d+)\]")
_BUSINESS_CITATION_RE = re.compile(r"\[B(\d+)\]", re.IGNORECASE)


def _append_execution_trace(
    context: WorkflowContext,
    step: str,
    status: str,
    summary: str,
) -> None:
    trace = context.metadata.setdefault("execution_trace", [])
    event = {"step": step, "status": status, "summary": summary}
    if isinstance(trace, list):
        for index, previous in enumerate(trace):
            if isinstance(previous, dict) and previous.get("step") == step:
                trace[index] = event
                break
        else:
            trace.append(event)
    progress_sink = context.metadata.get("process_sink")
    if progress_sink is not None:
        progress_sink.put_nowait(event)


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
            context.metadata["citations"] = []
            context.metadata["answer_basis"] = []
            context.metadata["retrieval_status"] = "blocked"
            context.metadata["execution_trace"] = []
            _append_execution_trace(context, "safety", "blocked", "输入未通过安全校验")
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
            context.next_node = (
                "query_rewrite"
                if context.metadata.get("requires_knowledge_base", True)
                else "answer"
            )
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
        context.metadata["retrieval_status"] = "not_called"
        context.metadata["answer_basis"] = ["conversation_context"]
        _append_execution_trace(context, "clarify", "waiting", "问题对象不明确，已请求用户确认")
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
        _append_execution_trace(
            context,
            "query_rewrite",
            "running",
            "正在生成知识库检索条件",
        )
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
        _append_execution_trace(context, "query_rewrite", "completed", "已生成专业资料检索条件")
        context.next_node = "retrieve"
        return context


class RetrieveNode(BaseWorkflowNode):
    """检索 + 重排：调用 RAG Pipeline，写入 retrieved_documents。"""

    name = "retrieve"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        pipeline = get_pipeline()
        query = context.metadata.get("search_query") or context.user_input or ""
        filters = context.metadata.get("filters")
        _append_execution_trace(
            context,
            "knowledge_retrieval",
            "running",
            "正在检索专业知识库",
        )
        try:
            docs = await pipeline.retrieve_and_rerank(query, filters=filters)
        except Exception as exc:  # noqa: BLE001
            logger.warning("检索失败，返回空结果：{}", exc)
            docs = []
            context.metadata["retrieval_status"] = "failed"
            _append_execution_trace(context, "knowledge_retrieval", "failed", "知识库检索失败")
        else:
            context.metadata["retrieval_status"] = "retrieved" if docs else "no_results"
            _append_execution_trace(
                context,
                "knowledge_retrieval",
                "completed",
                f"知识库检索完成，获得 {len(docs)} 个候选片段",
            )
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

    @staticmethod
    def _select_used_citations(
        answer: str,
        candidates: list[dict[str, Any]],
    ) -> tuple[str, list[dict[str, Any]]]:
        """仅保留答案正文真实引用且属于本次候选集的编号。"""

        used_indexes: list[int] = []
        for match in _INLINE_CITATION_RE.finditer(answer):
            index = int(match.group(1))
            if 1 <= index <= len(candidates) and index not in used_indexes:
                used_indexes.append(index)

        # 删除模型生成的越界数字引用，避免正文出现无法核验的来源编号。
        cleaned = _INLINE_CITATION_RE.sub(
            lambda match: match.group(0)
            if 1 <= int(match.group(1)) <= len(candidates)
            else "",
            answer,
        )
        selected: list[dict[str, Any]] = []
        seen: set[tuple[str, str, str]] = set()
        for index in used_indexes:
            citation = candidates[index - 1]
            key = (
                str(citation.get("knowledge_id", "")),
                str(citation.get("chapter", "")),
                str(citation.get("chunk_id", "")),
            )
            if key in seen:
                continue
            seen.add(key)
            selected.append(citation)
        return cleaned, selected

    @staticmethod
    def _select_used_business_evidence(answer: str, candidate_count: int) -> tuple[str, list[int]]:
        """提取答案实际标注的业务事实编号，并移除越界标注。"""

        used_indexes: list[int] = []
        for match in _BUSINESS_CITATION_RE.finditer(answer):
            index = int(match.group(1))
            if 1 <= index <= candidate_count and index not in used_indexes:
                used_indexes.append(index)
        cleaned = _BUSINESS_CITATION_RE.sub(
            lambda match: match.group(0).upper()
            if 1 <= int(match.group(1)) <= candidate_count
            else "",
            answer,
        )
        return cleaned, used_indexes

    @staticmethod
    def _keep_verified_markers(
        answer: str,
        knowledge_indexes: set[int],
        business_indexes: set[int],
    ) -> str:
        answer = _INLINE_CITATION_RE.sub(
            lambda match: match.group(0)
            if int(match.group(1)) in knowledge_indexes
            else "",
            answer,
        )
        return _BUSINESS_CITATION_RE.sub(
            lambda match: match.group(0).upper()
            if int(match.group(1)) in business_indexes
            else "",
            answer,
        )

    async def _verify_used_evidence(
        self,
        answer: str,
        docs: list[Any],
        business_evidence: list[dict[str, Any]],
        claimed_knowledge: list[int],
        claimed_business: list[int],
    ) -> tuple[set[int], set[int], bool]:
        """二次核验少量已声明证据；核验失败时不展示任何依据。"""

        if not claimed_knowledge and not claimed_business:
            return set(), set(), True
        knowledge_candidates = "\n".join(
            f"[{index}] {_as_untrusted_data(docs[index - 1].content)}"
            for index in claimed_knowledge
            if 1 <= index <= len(docs)
        )
        business_candidates = "\n".join(
            f"[B{index}] {_as_untrusted_data(str(business_evidence[index - 1]))}"
            for index in claimed_business
            if 1 <= index <= len(business_evidence)
        )
        try:
            boundary_system, _ = await get_prompt_messages("qa_evidence_boundary", {})
            system_prompt, user_prompt = await get_prompt_messages(
                "qa_evidence_verify",
                {
                    "answer": _as_untrusted_data(answer),
                    "knowledge_candidates": knowledge_candidates,
                    "business_candidates": business_candidates,
                },
            )
            result = await get_gateway().chat_structured(
                [
                    LLMMessage.system(boundary_system),
                    LLMMessage.system(system_prompt),
                    LLMMessage.user(user_prompt),
                ],
                schema_description=(
                    '{"supported_knowledge_indexes": [int], '
                    '"supported_business_indexes": [int]}'
                ),
                temperature=0.0,
            )
            if not result.success or not isinstance(result.data, dict):
                return set(), set(), False
            raw_knowledge = result.data.get("supported_knowledge_indexes", [])
            raw_business = result.data.get("supported_business_indexes", [])
            if not isinstance(raw_knowledge, list) or not isinstance(raw_business, list):
                return set(), set(), False
            knowledge = {
                item
                for item in raw_knowledge
                if isinstance(item, int) and not isinstance(item, bool) and item in claimed_knowledge
            }
            business = {
                item
                for item in raw_business
                if isinstance(item, int) and not isinstance(item, bool) and item in claimed_business
            }
            return knowledge, business, True
        except Exception as exc:  # noqa: BLE001
            logger.warning("答案依据二次核验失败，不展示引用：{}", exc)
            return set(), set(), False

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        pipeline = get_pipeline()
        docs = context.retrieved_documents
        citation_candidates: list[dict[str, Any]] = []
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
                citation_candidates.append(citation)
            knowledge_ctx = "\n\n".join(ctx_parts)
        else:
            if context.metadata.get("requires_knowledge_base", True):
                knowledge_ctx = "（本轮知识库未检索到可用资料；不得编造知识库依据。）"
            else:
                knowledge_ctx = "（本轮按用户意图调用业务功能，无需检索知识库。）"

        question = _as_untrusted_data(context.user_input or "")
        sink = context.metadata.get("stream_sink")
        _append_execution_trace(
            context,
            "answer",
            "running",
            "正在根据实际功能结果生成回答",
        )
        module_failure_only = bool(context.metadata.get("module_errors")) and not bool(
            context.metadata.get("business_evidence_count", 0)
        ) and not context.metadata.get("requires_knowledge_base", True)
        recommendation_no_candidate = any(
            isinstance(item, dict)
            and item.get("module") == "training_recommendation"
            and item.get("status") == "no_candidate"
            for item in context.metadata.get("business_outcomes", [])
        )
        recommendation_answer = self._build_recommendation_answer(
            context.metadata.get("business_evidence", [])
        )
        recommendation_only = (
            recommendation_answer
            and context.intent == "training_recommendation"
            and len(context.metadata.get("business_evidence", [])) == 1
        )
        if recommendation_only:
            answer = recommendation_answer
            if sink is not None:
                await sink.put(answer)
        elif recommendation_no_candidate and not context.metadata.get(
            "requires_knowledge_base", True
        ):
            answer = (
                "推荐功能已完成计算，但当前没有可用的已发布实训任务。"
                "请联系教师发布新的实训任务后再试。"
            )
            if sink is not None:
                await sink.put(answer)
        elif module_failure_only:
            failed_names = "、".join(
                str(item.get("module", "业务功能"))
                for item in context.metadata.get("module_errors", [])
                if isinstance(item, dict)
            )
            answer = f"对应业务功能暂时不可用（{failed_names or '未知功能'}），本轮未使用知识库结果替代，请稍后重试。"
            if sink is not None:
                await sink.put(answer)
        else:
            messages = await _build_answer_messages(context, knowledge_ctx, question)
            try:
                gw = get_gateway()
                if sink is not None:
                    if recommendation_answer:
                        await sink.put(recommendation_answer + "\n\n")
                    raw = await self._generate_streaming(gw, messages, sink)
                    context.metadata["streamed"] = True
                    # 引用信息由前端「引用来源」卡片展示；仅剥离模型自造的依据清单
                    answer = strip_model_citation_section(raw)
                else:
                    resp = await gw.chat(messages, temperature=0.2)
                    answer = strip_model_citation_section(resp.content)
                if recommendation_answer:
                    answer = recommendation_answer + "\n\n" + answer
            except Exception as exc:  # noqa: BLE001
                logger.error("答案生成失败：{}", exc)
                answer = "（答案生成服务暂不可用，请稍后重试。当前为教学模拟环境。）"
                if sink is not None:
                    await sink.put(answer)
        claimed_knowledge_indexes = list(
            dict.fromkeys(
                int(match.group(1))
                for match in _INLINE_CITATION_RE.finditer(answer)
                if 1 <= int(match.group(1)) <= len(citation_candidates)
            )
        )
        answer, _ = self._select_used_citations(answer, citation_candidates)
        answer, claimed_business_indexes = self._select_used_business_evidence(
            answer,
            int(context.metadata.get("business_evidence_count", 0)),
        )
        has_claimed_evidence = bool(
            claimed_knowledge_indexes or claimed_business_indexes
        )
        if has_claimed_evidence:
            _append_execution_trace(
                context,
                "evidence_check",
                "running",
                "正在核验回答采用的实际依据",
            )
        verified_knowledge, verified_business, verification_succeeded = await self._verify_used_evidence(
            answer,
            docs,
            context.metadata.get("business_evidence", []),
            claimed_knowledge_indexes,
            claimed_business_indexes,
        )
        answer = self._keep_verified_markers(
            answer,
            verified_knowledge,
            verified_business,
        )
        answer, used_citations = self._select_used_citations(answer, citation_candidates)
        answer, used_business_indexes = self._select_used_business_evidence(
            answer,
            int(context.metadata.get("business_evidence_count", 0)),
        )
        context.metadata["citations"] = used_citations
        context.metadata["used_business_evidence_indexes"] = used_business_indexes
        context.metadata["evidence_verification_succeeded"] = verification_succeeded
        answer_basis: list[str] = []
        if used_business_indexes or context.metadata.get("business_outcomes"):
            answer_basis.append("business_data")
        elif context.metadata.get("module_errors"):
            answer_basis.append("business_function_error")
        if used_citations:
            answer_basis.append("knowledge_base")
        if not answer_basis:
            answer_basis.append("conversation_context")
        context.metadata["answer_basis"] = answer_basis
        if context.metadata.get("requires_knowledge_base", True):
            prior_status = context.metadata.get("retrieval_status")
            if used_citations:
                context.metadata["retrieval_status"] = "used"
            elif prior_status == "retrieved":
                context.metadata["retrieval_status"] = "retrieved_not_used"
        else:
            context.metadata["retrieval_status"] = "not_called"
        if has_claimed_evidence:
            _append_execution_trace(
                context,
                "evidence_check",
                "completed" if verification_succeeded else "failed",
                (
                    "依据核验完成，采用"
                    f" {len(used_citations)} 条知识库依据、"
                    f"{len(used_business_indexes)} 条业务事实"
                    if verification_succeeded
                    else (
                        "依据核验失败，本轮不展示未经核验的依据"
                    )
                ),
            )
        _append_execution_trace(
            context,
            "answer",
            "failed" if module_failure_only else "completed",
            (
                "业务功能失败，已返回明确错误且未用知识库替代"
                if module_failure_only
                else "已基于实际执行结果生成回答"
            ),
        )
        context.metadata["answer"] = answer
        context.add_message("assistant", answer)
        context.next_node = "output_guard"
        return context

    @staticmethod
    def _build_recommendation_answer(
        business_evidence: list[dict[str, Any]],
    ) -> str:
        """从推荐服务的真实结果构造确定性回答，避免模型遗漏具体项目。"""

        for evidence_index, evidence in enumerate(business_evidence, 1):
            if not isinstance(evidence, dict) or evidence.get("type") != "training_recommendation":
                continue
            items = evidence.get("items", [])
            if not isinstance(items, list) or not items:
                return ""
            lines: list[str] = []
            for item in items[:3]:
                if not isinstance(item, dict):
                    continue
                title = str(item.get("title", "")).strip()
                if not title:
                    continue
                retry = item.get("mode") == "retry" or item.get("reason_code") == "retry"
                action = "复训" if retry else "实训"
                reason = str(item.get("reason", "")).strip()
                detail_parts = []
                if item.get("difficulty") is not None:
                    detail_parts.append(f"难度 {item['difficulty']}")
                if item.get("estimated_minutes") is not None:
                    detail_parts.append(f"预计 {item['estimated_minutes']} 分钟")
                detail = f"（{'，'.join(detail_parts)}）" if detail_parts else ""
                line = f"推荐{action}「{title}」{detail}"
                if reason:
                    line += f"：{reason}"
                lines.append(f"{line}[B{evidence_index}]。")
            if lines:
                heading = "当前已发布的新实训均已完成，建议优先复训：" if all(
                    isinstance(item, dict)
                    and (item.get("mode") == "retry" or item.get("reason_code") == "retry")
                    for item in items[:3]
                ) else "根据当前能力画像，推荐以下实训："
                return heading + "\n\n" + "\n".join(
                    f"{index}. {line}" for index, line in enumerate(lines, 1)
                )
        return ""

    async def _generate_streaming(self, gw, messages: list[LLMMessage], sink) -> str:
        """完整消费 LLM 流，逐块推送给路由层，返回累计回答文本。"""
        raw_parts: list[str] = []
        async for piece in gw.chat_stream(messages, temperature=0.2):
            if piece:
                await sink.put(piece)
                raw_parts.append(piece)
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
            context.metadata["answer_basis"] = []
            context.metadata["retrieval_status"] = "blocked"
            _append_execution_trace(context, "safety", "blocked", "回答未通过输出安全校验")
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
