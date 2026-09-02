"""统一配置中心。

所有配置通过环境变量 / .env 注入，业务代码禁止硬编码配置项。
模型名称、API Key、权重等均从此处读取。
"""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.enums import EvidenceSourceType


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
    position_browser_headless: bool = True
    position_browser_max_steps: int = 24
    position_browser_max_pages: int = 12
    position_browser_timeout_seconds: int = 30
    position_browser_min_interval_seconds: float = 1.5
    position_browser_source_timeout_seconds: int = 180

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

    # ---- 能力评价（P0-1：EMA 能力水平 + 证据置信度 + 成长 XP） ----
    # Ability Score 采用指数移动平均：new = old × (1 − α_eff) + evidence × α_eff，
    # α_eff = min(ability_alpha_max, ability_ema_alpha × evidence_weight × recency_weight)。
    # 低分证据必然拉低能力分，杜绝旧版"重复训练只涨不跌"问题。
    ability_ema_alpha: float = 0.30
    ability_alpha_max: float = 0.90
    # 证据来源权重（统一配置，禁止散落写死；数值 ∈ (0, 1]）
    ability_evidence_weight_knowledge_quiz: float = 0.50
    ability_evidence_weight_scenario_choice: float = 0.60
    ability_evidence_weight_scenario_diagnosis: float = 0.80
    ability_evidence_weight_operation_event: float = 1.00
    ability_evidence_weight_teacher_assessment: float = 1.00
    # 置信度分档：证据数 < medium_min → low；< high_min → medium；
    # ≥ high_min 且来源类型数 ≥ high_min_types → high
    ability_confidence_medium_min: int = 3
    ability_confidence_high_min: int = 8
    ability_confidence_high_min_types: int = 2
    # 成长 XP：投入度累计，与能力水平分离（"学了很多" ≠ "能力很强"）
    ability_xp_base_per_evidence: int = 10
    ability_xp_level_step: int = 100

    # ---- 自适应学习（P0-5 Phase 6，§42~§44：规则阈值全部入配置，不经 LLM） ----
    # 近期窗口：知识点掌握按最近 N 次作答；趋势对比取最近/前段各 M 条
    adaptive_recent_answer_window: int = 3
    adaptive_trend_window: int = 2
    # 趋势判定：近段与远段平均分之差超过该值记 improving/declining，否则 stable
    adaptive_trend_delta: float = 5.0
    # §43 证据优先链触发：薄弱(< adaptive_weak_threshold) 且置信度 ≥ medium
    # 且最近连续 ≥ count 条操作/诊断证据低于 low_score
    adaptive_weak_threshold: float = 60.0
    adaptive_evidence_low_score: float = 60.0
    adaptive_recent_op_low_count: int = 2
    # §44 安全优先：安全意识低于 floor 时安全补学置顶；
    # 难度 ≥ gate 的训练/仿真步骤附带先完成安全项的提醒
    adaptive_safety_score_floor: float = 80.0
    adaptive_safety_gate_difficulty: int = 3
    # 证据读取上限（仅取最近 N 条参与规则计算，避免全表扫描）
    adaptive_evidence_limit: int = 300

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

    def ability_evidence_weight(self, source_type: str) -> float:
        """按证据来源类型返回权重（唯一定义处，业务代码禁止另行写死）。

        未知来源类型直接抛错（fail-loud），避免静默使用错误权重。
        """
        weights = {
            EvidenceSourceType.knowledge_quiz: self.ability_evidence_weight_knowledge_quiz,
            EvidenceSourceType.scenario_choice: self.ability_evidence_weight_scenario_choice,
            EvidenceSourceType.scenario_diagnosis: self.ability_evidence_weight_scenario_diagnosis,
            EvidenceSourceType.operation_event: self.ability_evidence_weight_operation_event,
            EvidenceSourceType.teacher_assessment: self.ability_evidence_weight_teacher_assessment,
        }
        try:
            return weights[EvidenceSourceType(source_type)]
        except ValueError as exc:
            raise ValueError(f"未知能力证据来源类型: {source_type}") from exc

    @model_validator(mode="after")
    def _check_ability_eval(self) -> Settings:
        """能力评价参数合法性：alpha ∈ (0,1]，权重 ∈ (0,1]，置信度阈值递增。"""
        if not 0.0 < self.ability_ema_alpha <= 1.0:
            raise ValueError(f"ability_ema_alpha 必须 ∈ (0,1]，当前 {self.ability_ema_alpha}")
        if not 0.0 < self.ability_alpha_max <= 1.0:
            raise ValueError(f"ability_alpha_max 必须 ∈ (0,1]，当前 {self.ability_alpha_max}")
        evidence_weights = {
            "knowledge_quiz": self.ability_evidence_weight_knowledge_quiz,
            "scenario_choice": self.ability_evidence_weight_scenario_choice,
            "scenario_diagnosis": self.ability_evidence_weight_scenario_diagnosis,
            "operation_event": self.ability_evidence_weight_operation_event,
            "teacher_assessment": self.ability_evidence_weight_teacher_assessment,
        }
        for name, value in evidence_weights.items():
            if not 0.0 < value <= 1.0:
                raise ValueError(f"ability_evidence_weight_{name} 必须 ∈ (0,1]，当前 {value}")
        if not self.ability_confidence_medium_min < self.ability_confidence_high_min:
            raise ValueError("置信度阈值必须满足 medium_min < high_min")
        if self.ability_xp_level_step < 1 or self.ability_xp_base_per_evidence < 1:
            raise ValueError("成长 XP 参数必须 ≥ 1")
        return self

    @model_validator(mode="after")
    def _check_weights(self) -> Settings:
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
