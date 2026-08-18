"""RAG 引擎包（第三十二节）。

公开接口：
- get_pipeline() -> RAGPipeline  检索+重排+引用
- get_embedding_service() / get_reranker() / get_vector_store()
- parse_document / chunk_text / clean_text / build_citation

约束：仅做检索证据提供；不生成最终回答、不评分、不路由、不持久化。
"""

from __future__ import annotations

from app.rag.chunker import Chunk, chunk_text
from app.rag.citation import (
    append_verified_citation_section,
    build_citation,
    format_citation_section,
    format_citation_text,
    normalize_citations,
    split_before_model_citation_section,
    strip_model_citation_section,
)
from app.rag.cleaner import clean_text
from app.rag.embedding import EmbeddingService, get_embedding_service
from app.rag.parser import ParsedDocument, parse_document
from app.rag.pipeline import RAGPipeline, get_pipeline, reset_pipeline
from app.rag.reranker import RerankerService, get_reranker
from app.rag.store import InMemoryStore, QdrantStore, VectorStore, get_vector_store

__all__ = [
    "get_pipeline",
    "reset_pipeline",
    "RAGPipeline",
    "get_embedding_service",
    "EmbeddingService",
    "get_reranker",
    "RerankerService",
    "get_vector_store",
    "VectorStore",
    "QdrantStore",
    "InMemoryStore",
    "parse_document",
    "ParsedDocument",
    "chunk_text",
    "Chunk",
    "clean_text",
    "append_verified_citation_section",
    "strip_model_citation_section",
    "split_before_model_citation_section",
    "build_citation",
    "format_citation_section",
    "format_citation_text",
    "normalize_citations",
]
