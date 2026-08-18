"""面向 SSE 的安全句段缓冲。

模型分片不会直接暴露给客户端。只有形成完整句段、通过累计输出安全检查，
且不属于模型自行生成的“专业依据”段落时，才允许向下游发送。
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from app.rag import split_before_model_citation_section
from app.safety.guard import SafetyGuard, SafetyResult, get_safety_guard

_SENTENCE_BOUNDARY_RE = re.compile(r".*?(?:\r?\n|[。！？!?；;])", re.DOTALL)


@dataclass
class SafeStreamDecision:
    """一次模型分片经过安全缓冲后的放行结果。"""

    chunks: list[str] = field(default_factory=list)
    violation: SafetyResult | None = None


class SafeSentenceStreamer:
    """按完整句段检查并放行模型文本，避免危险 Token 抢先到达前端。"""

    def __init__(self, guard: SafetyGuard | None = None) -> None:
        self._guard = guard or get_safety_guard()
        self._pending = ""
        self._accepted = ""
        self._blocked = False
        self._suppress_citations = False

    @property
    def accepted_text(self) -> str:
        return self._accepted

    @property
    def blocked(self) -> bool:
        return self._blocked

    def feed(self, piece: str) -> SafeStreamDecision:
        """接收上游文本分片，并返回已经形成完整句段的安全增量。"""

        if self._blocked or self._suppress_citations or not piece:
            return SafeStreamDecision()
        self._pending += piece
        decision = SafeStreamDecision()
        while match := _SENTENCE_BOUNDARY_RE.match(self._pending):
            segment = match.group(0)
            self._pending = self._pending[len(segment) :]
            accepted = self._accept(segment)
            decision.chunks.extend(accepted.chunks)
            if accepted.violation is not None:
                decision.violation = accepted.violation
                break
        return decision

    def finish(self) -> SafeStreamDecision:
        """模型结束时检查最后一个没有句末标点的尾段。"""

        if self._blocked or self._suppress_citations or not self._pending:
            self._pending = ""
            return SafeStreamDecision()
        segment = self._pending
        self._pending = ""
        return self._accept(segment)

    def _accept(self, segment: str) -> SafeStreamDecision:
        visible, citation_started = split_before_model_citation_section(segment)
        if citation_started:
            self._suppress_citations = True
            self._pending = ""
        if not visible:
            return SafeStreamDecision()

        result = self._guard.check_output(self._accepted + visible)
        if not result.safe:
            self._blocked = True
            self._pending = ""
            return SafeStreamDecision(violation=result)

        self._accepted += visible
        return SafeStreamDecision(chunks=[visible])


__all__ = ["SafeSentenceStreamer", "SafeStreamDecision"]
