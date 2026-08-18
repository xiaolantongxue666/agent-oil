"""models 包：SQLAlchemy ORM 模型。

集中导入所有模型，使 Alembic autogenerate 与 Base.metadata 能发现全部表。
"""

from app.models.ability import (
    AbilityHistory,
    AbilityScore,
    ErrorRecord,
    LearningRecommendation,
)
from app.models.admin import AdminAuditLog, FeatureConfig
from app.models.base import PKMixin, TimestampMixin
from app.models.chat import ChatMessage, ChatSession
from app.models.curriculum import (
    CurriculumCourse,
    CurriculumProgram,
    IndustryEvidence,
    ProgramAdjustmentProposal,
)
from app.models.knowledge import KnowledgeChunk, KnowledgeEvidenceRelation, KnowledgeItem
from app.models.position import (
    Ability,
    JobTask,
    KnowledgePoint,
    Position,
    PositionAbilityRelation,
    SkillPoint,
    TaskAbilityRelation,
)
from app.models.position_market import (
    JobPostingSnapshot,
    PositionAnalysisRun,
    PositionDiscoveryRun,
)
from app.models.prompt import PromptTemplate, PromptTemplateRevision
from app.models.training import (
    EvaluationResult,
    StudentAnswer,
    TeachingPlan,
    TrainingChoiceAnswer,
    TrainingOption,
    TrainingQuestion,
    TrainingScenario,
    TrainingSession,
    TrainingTask,
)
from app.models.user import User
from app.models.workflow import WorkflowExecutionLog, WorkflowInstance

__all__ = [
    "Ability",
    "AdminAuditLog",
    "AbilityHistory",
    "AbilityScore",
    "ChatMessage",
    "ChatSession",
    "CurriculumCourse",
    "CurriculumProgram",
    "ErrorRecord",
    "FeatureConfig",
    "EvaluationResult",
    "JobTask",
    "JobPostingSnapshot",
    "IndustryEvidence",
    "KnowledgeChunk",
    "KnowledgeItem",
    "KnowledgeEvidenceRelation",
    "KnowledgePoint",
    "LearningRecommendation",
    "PKMixin",
    "Position",
    "PositionAnalysisRun",
    "PositionAbilityRelation",
    "PositionDiscoveryRun",
    "PromptTemplate",
    "PromptTemplateRevision",
    "ProgramAdjustmentProposal",
    "SkillPoint",
    "StudentAnswer",
    "TeachingPlan",
    "TaskAbilityRelation",
    "TimestampMixin",
    "TrainingScenario",
    "TrainingChoiceAnswer",
    "TrainingOption",
    "TrainingQuestion",
    "TrainingSession",
    "TrainingTask",
    "User",
    "WorkflowExecutionLog",
    "WorkflowInstance",
]
