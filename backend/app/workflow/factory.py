"""工作流工厂（第四十三节）。

按 workflow_type 装配引擎：
- "qa"：知识问答（intent→guard→rewrite→retrieve→answer→output_guard→done）
- "training"：AI 情境实训（strategy→scenario→answer→evaluate→follow_up→done）

LLM 仅在语言推理节点内被调用；路由与状态完全由引擎控制。
"""

from __future__ import annotations

from app.workflow.engine import WorkflowEngine
from app.workflow.nodes import qa_nodes, qa_routes, training_nodes, training_routes
from app.workflow.registry import NodeRegistry
from app.workflow.router import ConditionalRouter

_engines: dict[str, WorkflowEngine] = {}


def _build_qa_engine() -> WorkflowEngine:
    reg = NodeRegistry()
    for node in qa_nodes():
        reg.register(node)
    router = ConditionalRouter()
    qa_routes(router)
    return WorkflowEngine(reg, router=router, persistence=None, max_iterations=50)


def _build_training_engine() -> WorkflowEngine:
    reg = NodeRegistry()
    for node in training_nodes():
        reg.register(node)
    router = ConditionalRouter()
    training_routes(router)
    return WorkflowEngine(reg, router=router, persistence=None, max_iterations=100)


def get_engine(workflow_type: str) -> WorkflowEngine:
    """返回指定类型的工作流引擎单例。"""
    if workflow_type not in _engines:
        if workflow_type == "qa":
            _engines[workflow_type] = _build_qa_engine()
        elif workflow_type == "training":
            _engines[workflow_type] = _build_training_engine()
        else:
            raise ValueError(f"未知工作流类型: {workflow_type}")
    return _engines[workflow_type]


def reset_engines() -> None:
    """重置引擎缓存（测试用）。"""
    _engines.clear()


__all__ = ["get_engine", "reset_engines"]
