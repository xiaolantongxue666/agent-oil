"""共享的管理员治理工具，保证功能开关在业务入口真实生效。"""

from __future__ import annotations

from fastapi import HTTPException, status
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.admin import AdminAuditLog, FeatureConfig

FEATURE_DEFINITIONS = {
    "teacher_industry": {
        "name": "产业与培养方案",
        "description": "控制产业证据、岗位图谱与培养方案管理功能。",
        "visible_roles": ["teacher", "admin"],
    },
    "training": {
        "name": "实训与题库",
        "description": "控制学生实训与教师题库管理功能。",
        "visible_roles": ["student", "teacher", "admin"],
    },
    "analytics": {
        "name": "学情与数据分析",
        "description": "控制能力画像、教学统计与分析功能。",
        "visible_roles": ["teacher", "admin"],
    },
    "resources": {
        "name": "教学资源",
        "description": "控制知识库上传、审核与资源治理功能。",
        "visible_roles": ["teacher", "admin"],
    },
    "assistant": {
        "name": "智能助手",
        "description": "控制专业知识问答与智能助手功能。",
        "visible_roles": ["student", "teacher", "admin"],
    },
}

# 保留原有公开常量的结构，避免影响已有调用方。
DEFAULT_FEATURES = {
    key: list(definition["visible_roles"])
    for key, definition in FEATURE_DEFINITIONS.items()
}


async def ensure_default_features(session: AsyncSession) -> None:
    existing = {item.key for item in (await session.scalars(select(FeatureConfig))).all()}
    for key, roles in DEFAULT_FEATURES.items():
        if key not in existing:
            session.add(FeatureConfig(key=key, visible_roles=roles))
    await session.flush()


async def enforce_feature(session: AsyncSession, user: dict[str, str], key: str, *, write: bool = False) -> None:
    await ensure_default_features(session)
    feature = await session.scalar(select(FeatureConfig).where(FeatureConfig.key == key))
    if feature is None or not feature.enabled or user.get("role") not in (feature.visible_roles or []):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该功能当前不可用")
    if write and feature.read_only:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="该功能当前为只读")


async def audit(session: AsyncSession, actor_id: int, action: str, target_type: str, target_id: object, detail: dict | None = None) -> None:
    session.add(
        AdminAuditLog(
            actor_id=actor_id,
            action=action,
            target_type=target_type,
            target_id=str(target_id),
            detail=jsonable_encoder(detail or {}),
        )
    )
