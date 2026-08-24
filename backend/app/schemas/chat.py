"""专业知识问答 Schema。"""

from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class ChatRequest(BaseModel):
    message: str = Field(..., min_length=1, max_length=2000)
    session_id: int | None = None


class Citation(BaseModel):
    knowledge_id: str = ""
    title: str = ""
    source_name: str = ""
    source_no: str = ""
    chapter: str = ""
    page: int | None = None
    chunk_id: int | None = None
    is_teaching_simulation: bool = True


class ChatResponse(BaseModel):
    session_id: int
    answer: str
    citations: list[Citation] = Field(default_factory=list)
    retrieved_count: int = 0
    safety: dict[str, Any] | None = None
    intent: str = "knowledge_qa"
    intent_confidence: float = 1.0
    secondary_intents: list[str] = Field(default_factory=list)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    actions: list[dict[str, Any]] = Field(default_factory=list)
    trace_summary: list[str] = Field(default_factory=list)
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_status: str = "not_called"
    answer_basis: list[str] = Field(default_factory=list)
    ai_generated: bool = True


class ChatSessionOut(BaseModel):
    id: int
    title: str = ""
    message_count: int = 0
    owner_role: str = "student"
    created_at: str = ""

    model_config = {"from_attributes": True}


class ChatMessageOut(BaseModel):
    id: int
    role: str
    content: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    intent: str = ""
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    cards: list[dict[str, Any]] = Field(default_factory=list)
    execution_trace: list[dict[str, Any]] = Field(default_factory=list)
    retrieval_status: str = ""
    answer_basis: list[str] = Field(default_factory=list)
    retrieved_count: int = 0
    created_at: str = ""

    model_config = {"from_attributes": True}


__all__ = ["ChatRequest", "ChatResponse", "Citation", "ChatSessionOut", "ChatMessageOut"]
