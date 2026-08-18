"""专业知识问答路由 POST /api/chat。

全链路：用户消息 → QA 工作流（守卫→改写→检索→生成→输出守卫）→ 回答+引用。
LLM 仅做语言推理；路由/守卫/持久化由代码控制。

另提供 POST /api/chat/stream（SSE 安全句段流式输出），主要事件序列：
start/meta/status → 多条 delta → sources/meta → done；安全拦截时通过 replace 原子替换。
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from uuid import uuid4

from fastapi import APIRouter, HTTPException, status
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from app.api import ok
from app.api.deps import CurrentUser, DBSession
from app.core.logging import logger
from app.db.session import AsyncSessionLocal
from app.models.chat import ChatMessage, ChatSession
from app.rag import (
    normalize_citations,
    strip_model_citation_section,
)
from app.safety import build_safe_output_message, get_safety_guard
from app.safety.streaming import SafeSentenceStreamer
from app.schemas.chat import (
    ChatMessageOut,
    ChatRequest,
    ChatResponse,
    ChatSessionOut,
    Citation,
)
from app.services.admin_governance import enforce_feature
from app.services.learning_assistant import LearningAssistantService
from app.workflow.context import WorkflowContext
from app.workflow.factory import get_engine

router = APIRouter(prefix="/chat", tags=["chat"])
_assistant_service = LearningAssistantService()


def _title_from(msg: str) -> str:
    return (msg[:24] + "…") if len(msg) > 24 else msg


def _safety_outcome(raw: dict | None) -> dict | None:
    if raw is None:
        return None
    return {
        "safe": False,
        "reason": str(raw.get("reason", "内容未通过安全校验")),
        "category": str(raw.get("category", "unknown")),
    }


def _message_out(message: ChatMessage) -> dict:
    """将历史消息兼容地转换为输出，避免旧的异常引用 JSON 破坏会话。

    旧版本曾将「专业依据（系统核验）」段落写入正文，现改由前端
    「引用来源」卡片单独展示，读取时统一剥离存量段落避免重复。
    """

    citations = normalize_citations(message.citations)
    content = (
        strip_model_citation_section(message.content)
        if message.role == "assistant"
        else message.content
    )
    return ChatMessageOut(
        id=message.id,
        role=message.role,
        content=content,
        citations=citations,
        created_at=message.created_at.isoformat() if message.created_at else "",
    ).model_dump()


@router.post("", summary="知识问答")
async def chat(body: ChatRequest, user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "assistant", write=True)
    uid = int(user["user_id"])
    role = user.get("role", "student")
    # Personal business facts are never loaded before the existing safety guard.
    precheck = get_safety_guard().check_input(body.message)

    # 1. 会话：复用或新建（仅限当前角色自己的会话，教师/学生对话分开存储）
    if body.session_id:
        stmt = select(ChatSession).where(
            ChatSession.id == body.session_id,
            ChatSession.user_id == uid,
            ChatSession.owner_role == role,
        )
        sess = (await session.execute(stmt)).scalar_one_or_none()
        if not sess:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        sess = ChatSession(user_id=uid, owner_role=role, title=_title_from(body.message))
        session.add(sess)
        await session.flush()

    # 2. 先加载既有消息作为多轮上下文，再持久化本轮用户消息
    history = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == sess.id)
            .order_by(ChatMessage.id.desc())
            .limit(12)
        )
    ).scalars().all()
    history = list(reversed(history))
    session.add(ChatMessage(session_id=sess.id, role="user", content=body.message))

    assistant_result = None
    if precheck.safe:
        assistant_result = await _assistant_service.prepare(
            session,
            user_id=uid,
            role=user.get("role", "student"),
            message=body.message,
        )

    # 3. 运行 QA 工作流
    ctx = WorkflowContext(
        user_id=uid,
        session_id=str(sess.id),
        intent=assistant_result.intent if assistant_result else "knowledge_qa",
        mode="qa",
        current_node="intent",
        user_input=body.message,
        messages=[{"role": item.role, "content": item.content} for item in history],
        role=user.get("role", "student"),
        metadata=(
            {"controlled_business_facts": assistant_result.controlled_facts}
            if assistant_result else {}
        ),
    )
    engine = get_engine("qa")
    try:
        ctx = await engine.run("qa", ctx)
    except Exception as exc:  # noqa: BLE001
        logger.exception("QA 工作流执行失败")
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="问答处理失败") from exc

    answer = ctx.metadata.get("answer", "（无回答）")
    citations_raw = normalize_citations(ctx.metadata.get("citations"))
    citations = [Citation(**c) for c in citations_raw if isinstance(c, dict)]
    safety = _safety_outcome(
        ctx.metadata.get("safety_reject") or ctx.metadata.get("safety_reject_output")
    )
    if safety:
        # Do not expose personal-business UI affordances after either workflow guard rejects.
        assistant_result = None

    # 4. 持久化助手消息（含引用）
    assistant_msg = ChatMessage(
        session_id=sess.id,
        role="assistant",
        content=answer,
        citations=citations_raw,
        token_count=ctx.metadata.get("token_count", 0),
    )
    session.add(assistant_msg)
    await session.commit()

    resp = ChatResponse(
        session_id=sess.id,
        answer=answer,
        citations=citations,
        retrieved_count=len(ctx.retrieved_documents),
        safety=safety,
        intent=assistant_result.intent if assistant_result else "knowledge_qa",
        secondary_intents=assistant_result.secondary_intents if assistant_result else [],
        evidence=assistant_result.evidence if assistant_result else [],
        cards=assistant_result.cards if assistant_result else [],
        actions=assistant_result.actions if assistant_result else [],
        trace_summary=(assistant_result.trace if assistant_result else ["safety_blocked_before_business_data"]),
        ai_generated=True,
    )
    return ok(resp.model_dump())


def _sse_event(event: str, payload: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/stream", summary="知识问答（流式输出）")
async def chat_stream(
    body: ChatRequest, user: CurrentUser, session: DBSession
) -> StreamingResponse:
    await enforce_feature(session, user, "assistant", write=True)
    uid = int(user["user_id"])
    role = user.get("role", "student")
    precheck = get_safety_guard().check_input(body.message)

    # 1. 会话：复用或新建（仅限当前角色自己的会话，教师/学生对话分开存储）
    if body.session_id:
        stmt = select(ChatSession).where(
            ChatSession.id == body.session_id,
            ChatSession.user_id == uid,
            ChatSession.owner_role == role,
        )
        sess = (await session.execute(stmt)).scalar_one_or_none()
        if not sess:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    else:
        sess = ChatSession(user_id=uid, owner_role=role, title=_title_from(body.message))
        session.add(sess)
        await session.flush()

    # 2. 先加载既有消息作为多轮上下文，再持久化本轮用户消息
    history = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == sess.id)
            .order_by(ChatMessage.id.desc())
            .limit(12)
        )
    ).scalars().all()
    history = list(reversed(history))
    session.add(ChatMessage(session_id=sess.id, role="user", content=body.message))
    await session.commit()
    session_id = sess.id
    request_id = str(uuid4())

    assistant_result = None
    if precheck.safe:
        assistant_result = await _assistant_service.prepare(
            session,
            user_id=uid,
            role=user.get("role", "student"),
            message=body.message,
        )

    meta = {
        "session_id": session_id,
        "request_id": request_id,
        "intent": assistant_result.intent if assistant_result else "knowledge_qa",
        "secondary_intents": assistant_result.secondary_intents if assistant_result else [],
        "evidence": assistant_result.evidence if assistant_result else [],
        "cards": assistant_result.cards if assistant_result else [],
        "actions": assistant_result.actions if assistant_result else [],
        "trace_summary": (
            assistant_result.trace if assistant_result
            else ["safety_blocked_before_business_data"]
        ),
    }
    workflow_args = {
        "user_id": uid,
        "session_id": str(session_id),
        "intent": meta["intent"],
        "user_input": body.message,
        "history": [{"role": item.role, "content": item.content} for item in history],
        "role": role,
        "controlled_facts": (
            assistant_result.controlled_facts if assistant_result else ""
        ),
    }

    async def _event_stream() -> AsyncIterator[str]:
        # 有界队列将 LLM 生产速度和客户端消费速度连接起来，避免丢片或无限积压。
        sink: asyncio.Queue[str | None] = asyncio.Queue(maxsize=32)
        ctx = WorkflowContext(
            user_id=workflow_args["user_id"],
            session_id=workflow_args["session_id"],
            intent=workflow_args["intent"],
            mode="qa",
            current_node="intent",
            user_input=workflow_args["user_input"],
            messages=workflow_args["history"],
            role=workflow_args["role"],
            metadata={
                "controlled_business_facts": workflow_args["controlled_facts"],
                "stream_sink": sink,
            },
        )
        engine = get_engine("qa")

        async def _run_workflow() -> WorkflowContext:
            cancelled = False
            try:
                return await engine.run("qa", ctx)
            except asyncio.CancelledError:
                cancelled = True
                raise
            finally:
                # AnswerNode 只负责生产分片，工作流包装器统一发送结束哨兵。
                if not cancelled:
                    await sink.put(None)

        workflow_task = asyncio.create_task(_run_workflow())
        streamer = SafeSentenceStreamer()
        stream_violation = None

        yield _sse_event(
            "start",
            {"session_id": session_id, "request_id": request_id},
        )
        # 业务证据与跳转卡片要等完整输出安全校验后再下发。
        yield _sse_event(
            "meta",
            {
                "session_id": session_id,
                "request_id": request_id,
                "intent": meta["intent"],
            },
        )
        yield _sse_event(
            "status",
            {"request_id": request_id, "message": "正在检索专业资料并组织回答"},
        )

        try:
            while True:
                try:
                    piece = await asyncio.wait_for(sink.get(), timeout=15)
                except TimeoutError:
                    yield _sse_event(
                        "heartbeat",
                        {"request_id": request_id},
                    )
                    continue
                if piece is None:
                    break
                decision = streamer.feed(piece)
                for chunk in decision.chunks:
                    yield _sse_event(
                        "delta",
                        {"request_id": request_id, "content": chunk},
                    )
                if decision.violation is not None:
                    stream_violation = decision.violation
                    break

            if stream_violation is None:
                tail = streamer.finish()
                for chunk in tail.chunks:
                    yield _sse_event(
                        "delta",
                        {"request_id": request_id, "content": chunk},
                    )
                stream_violation = tail.violation

            if stream_violation is not None:
                workflow_task.cancel()
                await asyncio.gather(workflow_task, return_exceptions=True)
                answer = build_safe_output_message(stream_violation)
                safety = {
                    "safe": False,
                    "reason": stream_violation.reason,
                    "category": stream_violation.category,
                }
                citations_raw: list[dict] = []
                meta.update(
                    {
                        "retrieved_count": 0,
                        "citations": [],
                        "safety": safety,
                        "evidence": [],
                        "cards": [],
                        "actions": [],
                        "trace_summary": ["stream_output_safety_blocked"],
                    }
                )
                yield _sse_event(
                    "replace",
                    {"request_id": request_id, "content": answer, "safety": safety},
                )
            else:
                ctx = await workflow_task
                safety = _safety_outcome(
                    ctx.metadata.get("safety_reject")
                    or ctx.metadata.get("safety_reject_output")
                )
                citations_raw = normalize_citations(ctx.metadata.get("citations"))
                if safety:
                    citations_raw = []
                answer = ctx.metadata.get("answer", "（无回答）")
                meta.update(
                    {
                        "retrieved_count": len(ctx.retrieved_documents),
                        "citations": citations_raw,
                        "safety": safety,
                    }
                )
                if safety:
                    meta.update({"evidence": [], "cards": [], "actions": []})
                    yield _sse_event(
                        "replace",
                        {"request_id": request_id, "content": answer, "safety": safety},
                    )
                elif not ctx.metadata.get("streamed"):
                    # 澄清、安全输入拦截等不经过模型流的回答，以原子替换事件展示。
                    yield _sse_event(
                        "replace",
                        {"request_id": request_id, "content": answer, "safety": None},
                    )

            yield _sse_event(
                "sources",
                {
                    "request_id": request_id,
                    "retrieved_count": meta.get("retrieved_count", 0),
                    "citations": citations_raw,
                },
            )
            # 保留 meta 事件兼容既有客户端，同时在结束前发送最终元数据。
            yield _sse_event("meta", meta)

            # 仅完整结束或安全替换后的回答才进入历史记录。
            try:
                async with AsyncSessionLocal() as db:
                    db.add(
                        ChatMessage(
                            session_id=session_id,
                            role="assistant",
                            content=answer,
                            citations=citations_raw,
                            token_count=ctx.metadata.get("token_count", 0),
                        )
                    )
                    await db.commit()
            except Exception as exc:  # noqa: BLE001
                logger.error("流式问答助手消息持久化失败：{}", exc)

            yield _sse_event(
                "done",
                {
                    "answer": answer,
                    "session_id": session_id,
                    "request_id": request_id,
                    "completed": True,
                },
            )
        except asyncio.CancelledError:
            logger.info("客户端取消 QA 流式请求 request_id={}", request_id)
            raise
        except Exception:  # noqa: BLE001
            logger.exception("QA 流式工作流执行失败")
            yield _sse_event(
                "error",
                {"request_id": request_id, "message": "问答处理失败，请重试"},
            )
            yield _sse_event(
                "done",
                {
                    "answer": "",
                    "session_id": session_id,
                    "request_id": request_id,
                    "completed": False,
                },
            )
        finally:
            if not workflow_task.done():
                workflow_task.cancel()
                await asyncio.gather(workflow_task, return_exceptions=True)

    return StreamingResponse(
        _event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@router.get("/sessions", summary="我的问答会话列表")
async def list_sessions(user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "assistant")
    uid = int(user["user_id"])
    role = user.get("role", "student")
    stmt = (
        select(ChatSession)
        .options(selectinload(ChatSession.messages))
        .where(ChatSession.user_id == uid, ChatSession.owner_role == role)
        .order_by(ChatSession.updated_at.desc())
    )
    sessions = (await session.execute(stmt)).scalars().all()
    out = []
    for s in sessions:
        out.append(
            ChatSessionOut(
                id=s.id,
                title=s.title,
                message_count=len(s.messages),
                owner_role=s.owner_role,
                created_at=s.created_at.isoformat() if s.created_at else "",
            ).model_dump()
        )
    return ok(out)


@router.get("/sessions/{session_id}", summary="会话消息详情")
async def get_session(session_id: int, user: CurrentUser, session: DBSession) -> dict:
    await enforce_feature(session, user, "assistant")
    uid = int(user["user_id"])
    role = user.get("role", "student")
    stmt = select(ChatSession).where(
        ChatSession.id == session_id,
        ChatSession.user_id == uid,
        ChatSession.owner_role == role,
    )
    sess = (await session.execute(stmt)).scalar_one_or_none()
    if not sess:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="会话不存在")
    msgs = (
        await session.execute(
            select(ChatMessage)
            .where(ChatMessage.session_id == session_id)
            .order_by(ChatMessage.id)
        )
    ).scalars().all()
    out = [_message_out(message) for message in msgs]
    return ok(out)


__all__ = ["router"]
