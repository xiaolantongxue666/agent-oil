"""节点注册表。

集中注册所有节点实例，按 name 查找。引擎通过注册表获取下一节点。
"""

from __future__ import annotations

from app.workflow.exceptions import WorkflowError
from app.workflow.nodes.base import BaseWorkflowNode


class NodeRegistry:
    """节点注册表。"""

    def __init__(self) -> None:
        self._nodes: dict[str, BaseWorkflowNode] = {}

    def register(self, node: BaseWorkflowNode) -> BaseWorkflowNode:
        if not node.name:
            raise WorkflowError(f"节点未设置 name: {node!r}")
        if node.name in self._nodes:
            raise WorkflowError(f"节点已注册: {node.name}")
        self._nodes[node.name] = node
        return node

    def get(self, name: str) -> BaseWorkflowNode:
        if name not in self._nodes:
            raise WorkflowError(f"未知节点: {name}")
        return self._nodes[name]

    def has(self, name: str) -> bool:
        return name in self._nodes

    def __len__(self) -> int:
        return len(self._nodes)


__all__ = ["NodeRegistry"]
