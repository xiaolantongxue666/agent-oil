"""统一配置中心。

所有配置通过环境变量 / .env 注入，业务代码禁止硬编码配置项。
模型名称、API Key、权重等均从此处读取。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """全局配置。从 .env / 环境变量加载。"""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ---- 应用 ----
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "油训智安"
    app_port: int = 8000
    app_debug: bool = True
    cors_origins: str = "http://localhost:5173"

    # ---- 数据库 ----
    database_url: str = (
        "postgresql+asyncpg://oiltrain:oiltrain123@localhost:5432/oiltrain"
    )

    # ---- JWT ----
    jwt_secret: str = "change-me-to-a-long-random-secret-string"
    jwt_algorithm: str = "HS256"
    jwt_access_token_expire_minutes: int = 1440

    # ---- 阿里云百炼 ----
    bailian_api_key: str = ""
    bailian_base_url: str = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    bailian_model: str = "qwen-plus"
    bailian_temperature: float = 0.2
    bailian_timeout: int = 60
    bailian_max_retries: int = 3
    llm_use_mock: bool = True

    # ---- Qdrant ----
    qdrant_url: str = "http://localhost:6333"
    qdrant_collection: str = "oil_train_safe"
    qdrant_api_key: str = ""

    # ---- Embedding ----
    embedding_backend: Literal["local", "api"] = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_api_key: str = ""
    embedding_base_url: str = ""
    embedding_dim: int = 1024

    # ---- Reranker ----
    reranker_backend: Literal["local", "api"] = "local"
    reranker_model: str = "BAAI/bge-reranker-base"
    reranker_api_key: str = ""
    reranker_base_url: str = ""

    # ---- 岗位公开数据发现 ----
    job_search_url: str = "https://cn.bing.com/search"
    job_search_timeout: int = 20
    job_search_max_results: int = 20

    # ---- 文件上传 ----
    upload_dir: str = "uploads"
    upload_max_size_mb: int = 5
    upload_allowed_extensions: str = "pdf,docx,txt,md,markdown"
    document_max_pages: int = 60
    document_max_text_chars: int = 120_000
    document_max_archive_entries: int = 2_000
    document_max_uncompressed_bytes: int = 30_000_000
    document_max_compression_ratio: int = 100

    # ---- RAG ----
    rag_retrieve_top_k: int = 20
    rag_rerank_top_k: int = 5
    rag_chunk_size: int = 512
    rag_chunk_overlap: int = 64
    rag_min_relevance: float = 0.3

    # ---- 实训 ----
    structured_output_max_retries: int = 2

    # ---- 混合评分权重 ----
    eval_rule_weight: float = 0.4
    eval_semantic_weight: float = 0.3
    eval_llm_weight: float = 0.3

    # ---- 六维能力权重 ----
    ability_weight_process: float = 0.20
    ability_weight_equipment: float = 0.15
    ability_weight_instrument: float = 0.15
    ability_weight_abnormal: float = 0.20
    ability_weight_safety: float = 0.20
    ability_weight_recording: float = 0.10

    # ---- 线上判断 ----
    @property
    def llm_available(self) -> bool:
        """是否具备真实 LLM 调用条件。"""
        return bool(self.bailian_api_key) and not self.llm_use_mock

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    @property
    def allowed_extensions(self) -> set[str]:
        return {e.strip().lower().lstrip(".") for e in self.upload_allowed_extensions.split(",") if e.strip()}

    @model_validator(mode="after")
    def _check_weights(self) -> "Settings":
        total_eval = (
            self.eval_rule_weight + self.eval_semantic_weight + self.eval_llm_weight
        )
        if abs(total_eval - 1.0) > 0.001:
            raise ValueError(f"混合评分权重之和必须为 1.0，当前为 {total_eval}")
        total_ability = (
            self.ability_weight_process
            + self.ability_weight_equipment
            + self.ability_weight_instrument
            + self.ability_weight_abnormal
            + self.ability_weight_safety
            + self.ability_weight_recording
        )
        if abs(total_ability - 1.0) > 0.001:
            raise ValueError(f"六维能力权重之和必须为 1.0，当前为 {total_ability}")
        return self

    @field_validator("jwt_secret")
    @classmethod
    def _warn_default_secret(cls, v: str) -> str:
        if v == "change-me-to-a-long-random-secret-string":
            # 仅在非生产环境告警，不阻断启动
            import warnings

            warnings.warn("使用默认 JWT_SECRET，生产环境必须修改。", stacklevel=2)
        return v


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回单例 Settings。"""
    return Settings()  # type: ignore[call-arg]
