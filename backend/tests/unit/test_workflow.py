"""Workflow Engine 单元测试（第六十六节）。

覆盖：基本节点 / 条件路由 / WAITING_INPUT / Follow-Up / 最大循环次数 / Node Error / Workflow Resume
不依赖数据库与外部服务（persistence=None 的内存引擎）。
"""

from __future__ import annotations

import pytest

from app.workflow.context import WorkflowContext
from app.workflow.engine import WorkflowEngine
from app.workflow.enums import WorkflowState
from app.workflow.exceptions import RetryableNodeError, WorkflowError
from app.workflow.nodes.base import BaseWorkflowNode
from app.workflow.registry import NodeRegistry
from app.workflow.router import ConditionalRouter


# ---------- 测试用节点 ----------
class SetNextNode(BaseWorkflowNode):
    """设置 next_node 的通用节点。"""

    def __init__(self, name: str, nxt: str | None, mark: str | None = None) -> None:
        self.name = name
        self._nxt = nxt
        self._mark = mark

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.next_node = self._nxt
        if self._mark:
            context.metadata["visited"] = context.metadata.get("visited", [])
            if isinstance(context.metadata["visited"], list):
                context.metadata["visited"].append(self._mark)
        return context


class BranchNode(BaseWorkflowNode):
    """不设 next_node，依赖条件路由。"""

    name = "branch"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.metadata.setdefault("visited", [])
        if isinstance(context.metadata["visited"], list):
            context.metadata["visited"].append("branch")
        return context


class WaitNode(BaseWorkflowNode):
    """无学生答案时进入 WAITING_INPUT；有答案则放行。"""

    name = "wait_input"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        if not context.student_answer:
            context.state = WorkflowState.WAITING_INPUT
            context.add_message("assistant", "请回答：...")
            context.next_node = None
        else:
            context.attempt_count += 1
            context.next_node = "eval"
        return context


class EvalNode(BaseWorkflowNode):
    """模拟评价：第 attempt 次 need_follow_up，超过 max 则结束。"""

    name = "eval"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.metadata.setdefault("visited", [])
        if isinstance(context.metadata["visited"], list):
            context.metadata["visited"].append("eval")
        need_follow_up = context.attempt_count <= context.max_follow_ups
        context.next_node = "follow_up" if need_follow_up else "done"
        return context


class FollowUpNode(BaseWorkflowNode):
    name = "follow_up"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.follow_up_count += 1
        if context.follow_up_count > context.max_follow_ups:
            raise WorkflowError("追问超上限")
        context.student_answer = ""  # 清空，等待下一轮
        context.state = WorkflowState.WAITING_INPUT
        context.next_node = "wait_input"  # 恢复点：回到学生作答节点
        context.add_message("assistant", f"追问第 {context.follow_up_count} 次：...")
        return context


class DoneNode(BaseWorkflowNode):
    name = "done"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.score = 88.0
        context.state = WorkflowState.COMPLETED
        context.next_node = None
        return context


class ErrorNode(BaseWorkflowNode):
    name = "error_node"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        raise WorkflowError("故意失败")


class LoopNode(BaseWorkflowNode):
    name = "loop"

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        context.next_node = "loop"  # 永远指向自己
        return context


class RetryOnceNode(BaseWorkflowNode):
    name = "retry_once"
    _calls = 0

    async def execute(self, context: WorkflowContext) -> WorkflowContext:
        type(self)._calls += 1
        if type(self)._calls < 2:
            raise RetryableNodeError("首次失败，可重试")
        context.next_node = "done"
        return context


# ---------- fixtures ----------
def _registry(*nodes: BaseWorkflowNode) -> NodeRegistry:
    reg = NodeRegistry()
    for n in nodes:
        reg.register(n)
    return reg


@pytest.fixture
def engine_factory():
    def _make(registry: NodeRegistry, router: ConditionalRouter | None = None, **kw) -> WorkflowEngine:
        return WorkflowEngine(registry, router=router, persistence=None, **kw)

    return _make


# ---------- 测试 ----------
async def test_basic_linear_flow(engine_factory):
    reg = _registry(
        SetNextNode("a", "b", "a"),
        SetNextNode("b", None, "b"),
    )
    eng = engine_factory(reg)
    ctx = WorkflowContext(current_node="a", mode="qa")
    result = await eng.run("qa", ctx)
    assert result.state == WorkflowState.COMPLETED
    assert result.metadata["visited"] == ["a", "b"]


async def test_conditional_routing(engine_factory):
    reg = _registry(BranchNode(), SetNextNode("path_yes", None, "yes"), SetNextNode("path_no", None, "no"))
    router = ConditionalRouter()
    router.add_route("branch", "path_yes", lambda c: c.metadata.get("flag") == "yes")
    router.set_default("branch", "path_no")
    eng = engine_factory(reg, router)

    ctx_yes = WorkflowContext(current_node="branch", mode="qa", metadata={"flag": "yes"})
    res_yes = await eng.run("qa", ctx_yes)
    assert res_yes.metadata["visited"][-1] == "yes"

    ctx_no = WorkflowContext(current_node="branch", mode="qa", metadata={"flag": "no"})
    res_no = await eng.run("qa", ctx_no)
    assert res_no.metadata["visited"][-1] == "no"


async def test_waiting_input_pause(engine_factory):
    reg = _registry(WaitNode(), EvalNode(), FollowUpNode(), DoneNode())
    eng = engine_factory(reg)
    ctx = WorkflowContext(current_node="wait_input", mode="training", max_follow_ups=2)
    res = await eng.run("training", ctx)
    assert res.state == WorkflowState.WAITING_INPUT
    assert res.attempt_count == 0  # 未消费答案


async def test_follow_up_loop_and_done(engine_factory):
    reg = _registry(WaitNode(), EvalNode(), FollowUpNode(), DoneNode())
    eng = engine_factory(reg)
    ctx = WorkflowContext(current_node="wait_input", mode="training", max_follow_ups=2)

    # 轮1
    ctx = await eng.run("training", ctx)
    assert ctx.state == WorkflowState.WAITING_INPUT
    ctx.student_answer = "学生第一轮回答"
    ctx = await eng.resume("training", ctx)
    assert ctx.state == WorkflowState.WAITING_INPUT  # 触发追问1
    assert ctx.follow_up_count == 1

    # 轮2
    ctx.student_answer = "学生第二轮回答"
    ctx = await eng.resume("training", ctx)
    assert ctx.follow_up_count == 2
    assert ctx.state == WorkflowState.WAITING_INPUT  # 触发追问2

    # 轮3：达到 max_follow_ups，eval 不再追问 → done
    ctx.student_answer = "学生第三轮回答"
    ctx = await eng.resume("training", ctx)
    assert ctx.state == WorkflowState.COMPLETED
    assert ctx.score == 88.0


async def test_max_follow_up_exceeded(engine_factory):
    reg = _registry(WaitNode(), EvalNode(), FollowUpNode(), DoneNode())
    eng = engine_factory(reg)
    # max_follow_ups=0 时第一次 eval 即应 done（不追问）
    ctx = WorkflowContext(current_node="wait_input", mode="training", max_follow_ups=0)
    ctx.student_answer = "答"
    ctx = await eng.run("training", ctx)
    assert ctx.state == WorkflowState.COMPLETED


async def test_node_error_marks_failed(engine_factory):
    reg = _registry(ErrorNode())
    eng = engine_factory(reg)
    ctx = WorkflowContext(current_node="error_node", mode="qa")
    res = await eng.run("qa", ctx)
    assert res.state == WorkflowState.FAILED
    assert "故意失败" in res.error


async def test_infinite_loop_guard(engine_factory):
    reg = _registry(LoopNode())
    eng = engine_factory(reg, max_iterations=5)
    ctx = WorkflowContext(current_node="loop", mode="qa")
    res = await eng.run("qa", ctx)
    assert res.state == WorkflowState.FAILED
    assert "最大迭代次数" in res.error


async def test_workflow_resume(engine_factory):
    """WAITING_INPUT → 序列化为 JSON → 恢复 → resume 继续至完成。"""
    reg = _registry(WaitNode(), EvalNode(), FollowUpNode(), DoneNode())
    eng = engine_factory(reg)
    ctx = WorkflowContext(current_node="wait_input", mode="training", max_follow_ups=0)
    ctx = await eng.run("training", ctx)
    assert ctx.state == WorkflowState.WAITING_INPUT
    # 模拟序列化为 JSON 再恢复（中断恢复）
    dumped = ctx.to_json()
    restored = WorkflowContext.from_json(dumped)
    restored.student_answer = "恢复后的回答"
    res = await eng.resume("training", restored)
    assert res.state == WorkflowState.COMPLETED
    assert res.attempt_count == 1


async def test_retry_on_retryable_error(engine_factory):
    RetryOnceNode._calls = 0
    reg = _registry(RetryOnceNode(), DoneNode())
    eng = engine_factory(reg, max_retries=3)
    ctx = WorkflowContext(current_node="retry_once", mode="qa")
    res = await eng.run("qa", ctx)
    assert res.state == WorkflowState.COMPLETED
    assert RetryOnceNode._calls == 2  # 重试一次后成功
