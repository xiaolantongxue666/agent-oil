"""管理员总览、用户、功能开关和治理审计接口。"""

from __future__ import annotations

import json

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select

from app.api import ok
from app.api.deps import AdminUser, DBSession
from app.core.enums import UserRole
from app.models.admin import AdminAuditLog, FeatureConfig
from app.models.curriculum import CurriculumProgram
from app.models.knowledge import KnowledgeItem
from app.models.position import Position
from app.models.training import TrainingTask
from app.models.user import User
from app.services.admin_governance import (
    FEATURE_DEFINITIONS,
    audit,
    ensure_default_features,
)

router = APIRouter(prefix="/admin", tags=["admin"])


class UserPatch(BaseModel):
    real_name: str | None = Field(None, max_length=64)
    role: UserRole | None = None
    student_no: str | None = Field(None, max_length=32)
    class_name: str | None = Field(None, max_length=64)
    is_active: bool | None = None


class FeaturePatch(BaseModel):
    enabled: bool | None = None
    read_only: bool | None = None
    visible_roles: list[UserRole] | None = None
    reason: str | None = Field(None, max_length=2000)
    change_reason: str | None = Field(None, max_length=2000)


def _user_out(item: User) -> dict:
    return {
        "id": item.id,
        "username": item.username,
        "real_name": item.real_name,
        "role": item.role.value if hasattr(item.role, "value") else str(item.role),
        "student_no": item.student_no,
        "class_name": item.class_name,
        "is_active": item.is_active,
        "created_at": item.created_at,
        "updated_at": item.updated_at,
    }


def _feature_out(item: FeatureConfig) -> dict:
    definition = FEATURE_DEFINITIONS.get(item.key, {})
    return {
        "code": item.key,
        "key": item.key,
        "name": definition.get("name", item.key),
        "description": definition.get("description", "自定义功能配置。"),
        "enabled": item.enabled,
        "read_only": item.read_only,
        "visible_roles": item.visible_roles or [],
        "version": item.version,
        "change_reason": item.reason,
        "reason": item.reason,
        "updated_by": item.updated_by,
        "updated_at": item.updated_at,
    }


def _audit_out(
    item: AdminAuditLog,
    actor_real_name: str | None = None,
    actor_username: str | None = None,
) -> dict:
    actor_name = actor_real_name or actor_username
    if not actor_name:
        actor_name = "系统" if item.actor_id is None else f"用户#{item.actor_id}"
    detail = json.dumps(item.detail or {}, ensure_ascii=False, sort_keys=True)
    return {
        "id": item.id,
        "actor_id": item.actor_id,
        "actor_name": actor_name,
        "action": item.action,
        "resource_type": item.target_type,
        "resource_id": item.target_id or None,
        "target_type": item.target_type,
        "target_id": item.target_id,
        "detail": detail,
        "created_at": item.created_at,
    }


async def _recent_audits(session: DBSession, limit: int) -> list[dict]:
    rows = (
        await session.execute(
            select(AdminAuditLog, User.real_name, User.username)
            .outerjoin(User, User.id == AdminAuditLog.actor_id)
            .order_by(AdminAuditLog.id.desc())
            .limit(limit)
        )
    ).all()
    return [_audit_out(item, real_name, username) for item, real_name, username in rows]


@router.get("/overview")
async def overview(user: AdminUser, session: DBSession) -> dict:
    del user
    await ensure_default_features(session)
    role_counts = {role.value: 0 for role in UserRole}
    for role, count in (await session.execute(select(User.role, func.count(User.id)).group_by(User.role))).all():
        role_key = role.value if hasattr(role, "value") else str(role)
        role_counts[role_key] = count
    total_users = sum(role_counts.values())
    active_users = await session.scalar(
        select(func.count(User.id)).where(User.is_active.is_(True))
    ) or 0
    features = (await session.scalars(select(FeatureConfig))).all()
    resources = {
        "knowledge_items": await session.scalar(select(func.count(KnowledgeItem.id))) or 0,
        "positions": await session.scalar(select(func.count(Position.id))) or 0,
        "training_tasks": await session.scalar(select(func.count(TrainingTask.id))) or 0,
        "published_programs": await session.scalar(
            select(func.count(CurriculumProgram.id)).where(
                CurriculumProgram.status == "published"
            )
        ) or 0,
    }
    return ok(
        {
            "users": {
                "total": total_users,
                "student": role_counts[UserRole.student.value],
                "teacher": role_counts[UserRole.teacher.value],
                "admin": role_counts[UserRole.admin.value],
                "active": active_users,
            },
            "resources": resources,
            "features": {
                "enabled": sum(1 for feature in features if feature.enabled),
                "total": len(features),
            },
            "recent_audits": await _recent_audits(session, 10),
            # 兼容旧管理端读取的汇总字段。
            "active_users": active_users,
            "audit_logs": await session.scalar(select(func.count(AdminAuditLog.id))) or 0,
        }
    )


@router.get("/users")
async def list_users(user: AdminUser, session: DBSession) -> dict:
    del user
    items = (await session.scalars(select(User).order_by(User.id))).all()
    return ok([_user_out(item) for item in items])


@router.patch("/users/{user_id}")
async def update_user(user_id: int, body: UserPatch, user: AdminUser, session: DBSession) -> dict:
    target = await session.get(User, user_id)
    if target is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="用户不存在")
    payload = body.model_dump(exclude_unset=True)
    if any(
        field in payload and payload[field] is None
        for field in ("role", "real_name", "is_active")
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="角色、姓名和启用状态不能为 null",
        )
    actor_id = int(user["user_id"])
    if user_id == actor_id and payload.get("is_active") is False:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能停用自己")
    current_role = target.role.value if hasattr(target.role, "value") else str(target.role)
    losing_admin = current_role == "admin" and (payload.get("is_active") is False or payload.get("role") not in (None, UserRole.admin))
    if losing_admin:
        active_admin_ids = (
            await session.scalars(
                select(User.id)
                .where(User.role == UserRole.admin, User.is_active.is_(True))
                .with_for_update()
            )
        ).all()
        if len(active_admin_ids) <= 1:
            raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="不能停用或降级最后一个有效管理员")
    audit_payload = dict(payload)
    if isinstance(audit_payload.get("role"), UserRole):
        audit_payload["role"] = audit_payload["role"].value
    for key, value in payload.items():
        setattr(target, key, value)
    await audit(session, actor_id, "user.update", "user", user_id, audit_payload)
    await session.flush()
    await session.refresh(target)
    return ok(_user_out(target))


@router.get("/features")
async def list_features(user: AdminUser, session: DBSession) -> dict:
    del user
    await ensure_default_features(session)
    return ok([_feature_out(item) for item in (await session.scalars(select(FeatureConfig).order_by(FeatureConfig.key))).all()])


@router.put("/features/{key}")
async def update_feature(key: str, body: FeaturePatch, user: AdminUser, session: DBSession) -> dict:
    await ensure_default_features(session)
    feature = await session.scalar(select(FeatureConfig).where(FeatureConfig.key == key))
    if feature is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="功能不存在")
    payload = body.model_dump(exclude_unset=True)
    if any(
        field in payload and payload[field] is None
        for field in ("enabled", "read_only")
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="功能启用和只读状态不能为 null",
        )
    if "change_reason" in payload:
        payload["reason"] = payload.pop("change_reason") or ""
    elif "reason" in payload:
        payload["reason"] = payload["reason"] or ""
    if "visible_roles" in payload:
        payload["visible_roles"] = [role.value for role in (payload["visible_roles"] or [])]
    for field, value in payload.items():
        setattr(feature, field, value)
    feature.version += 1
    feature.updated_by = int(user["user_id"])
    await audit(session, int(user["user_id"]), "feature.update", "feature", key, payload)
    await session.flush()
    await session.refresh(feature)
    return ok(_feature_out(feature))


@router.get("/audit-logs")
async def audit_logs(user: AdminUser, session: DBSession, limit: int = Query(100, ge=1, le=500)) -> dict:
    del user
    return ok(await _recent_audits(session, limit))


# ---------- LLM 运行时配置 ----------

_LLM_KEY_MAP = {
    "provider": "llm_provider",
    "model": "llm_model",
    "base_url": "llm_base_url",
    "api_key": "llm_api_key",
    "temperature": "llm_temperature",
    "timeout": "llm_timeout",
    "max_retries": "llm_max_retries",
    "use_mock": "llm_use_mock",
}

_LLM_DESCRIPTIONS = {
    "llm_provider": "模型服务提供方 (bailian / spark / mock)",
    "llm_model": "模型标识（如 qwen-plus / generalv3.5）",
    "llm_base_url": "模型服务 Base URL",
    "llm_api_key": "API Key（敏感字段，明文存储，由审计日志保障）",
    "llm_temperature": "生成温度 (0.0 ~ 1.0)",
    "llm_timeout": "单次调用超时秒数",
    "llm_max_retries": "重试次数",
    "llm_use_mock": "是否强制使用 Mock（true / false）",
}


def _mask_api_key(value: str) -> str:
    if not value:
        return "(未配置，将使用 .env 默认)"
    if len(value) <= 8:
        return value[:2] + "****" + value[-2:]
    return value[:4] + "..." + value[-4:]


class LlmConfigUpdateBody(BaseModel):
    provider: str | None = Field(None, max_length=32)
    model: str | None = Field(None, max_length=128)
    base_url: str | None = Field(None, max_length=512)
    api_key: str | None = Field(None, max_length=2048)
    temperature: float | None = Field(None, ge=0.0, le=2.0)
    timeout: int | None = Field(None, ge=1, le=600)
    max_retries: int | None = Field(None, ge=0, le=10)
    use_mock: bool | None = None


@router.get("/llm-config", summary="获取当前生效的 LLM 配置")
async def get_llm_config(user: AdminUser, session: DBSession) -> dict:
    del user
    from app.core.config import get_settings
    from app.models.admin import SystemSetting
    from app.services.admin_governance import ensure_default_features  # noqa: F401  仅保留导入一致性

    settings = get_settings()
    rows = (
        await session.scalars(
            select(SystemSetting).where(SystemSetting.category == "llm")
        )
    ).all()
    db_map = {row.key: row for row in rows}

    def effective(env_value, db_key: str):
        row = db_map.get(db_key)
        return (row.value if row and row.value != "" else env_value)

    api_key_effective = str(effective(settings.bailian_api_key, "llm_api_key"))
    use_mock_effective = str(effective(settings.llm_use_mock, "llm_use_mock")).lower() in ("1", "true", "yes")
    provider_effective = str(effective("bailian" if api_key_effective else "mock", "llm_provider")).lower()
    if provider_effective not in ("bailian", "spark", "mock"):
        provider_effective = "bailian"
    if use_mock_effective or not api_key_effective:
        provider_effective = "mock"

    latest_updated_at = ""
    if rows:
        latest_updated_at = max(
            (row.updated_at for row in rows if row.updated_at),
            default=None,
        )
        latest_updated_at = latest_updated_at.isoformat() if latest_updated_at else ""

    return ok(
        {
            "provider": provider_effective,
            "model": str(effective(settings.bailian_model, "llm_model")),
            "base_url": str(effective(settings.bailian_base_url, "llm_base_url")),
            "api_key_masked": _mask_api_key(api_key_effective),
            "api_key_configured": bool(api_key_effective),
            "temperature": float(effective(settings.bailian_temperature, "llm_temperature")),
            "timeout": int(effective(settings.bailian_timeout, "llm_timeout")),
            "max_retries": int(effective(settings.bailian_max_retries, "llm_max_retries")),
            "use_mock": use_mock_effective,
            "has_db_override": bool(db_map),
            "last_updated_at": latest_updated_at,
        }
    )


@router.put("/llm-config", summary="保存 LLM 运行时配置（即时生效）")
async def update_llm_config(
    body: LlmConfigUpdateBody,
    user: AdminUser,
    session: DBSession,
) -> dict:
    from app.llm.gateway import refresh_runtime_llm_config, reset_gateway
    from app.models.admin import SystemSetting

    actor_id = int(user["user_id"])
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未提供任何配置项")
    saved: dict[str, str] = {}
    for field_name, value in payload.items():
        db_key = _LLM_KEY_MAP.get(field_name)
        if db_key is None:
            continue
        if field_name == "use_mock":
            str_value = "true" if bool(value) else "false"
        else:
            str_value = "" if value is None else str(value)
        existing = await session.scalar(select(SystemSetting).where(SystemSetting.key == db_key))
        if existing is None:
            existing = SystemSetting(
                key=db_key,
                category="llm",
                description=_LLM_DESCRIPTIONS.get(db_key, ""),
            )
            session.add(existing)
        existing.value = str_value
        existing.version = int(getattr(existing, "version", 1) or 1) + 1
        existing.updated_by = actor_id
        saved[field_name] = _mask_api_key(str_value) if field_name == "api_key" else str_value
    await session.flush()
    # 审计（API Key 已脱敏）
    await audit(session, actor_id, "llm_config.update", "system_setting", "llm", saved)
    # 重新加载内存 + 重置网关单例，下次调用即用新配置
    await refresh_runtime_llm_config(session)
    await reset_gateway()
    await session.commit()
    return ok({"saved": saved, "notice": "配置已保存并热更新，下次模型调用立即生效"})


@router.post("/llm-config/test", summary="用当前配置进行一次 LLM 连接测试")
async def test_llm_config(user: AdminUser, session: DBSession) -> dict:
    del user, session
    from app.llm.gateway import get_gateway

    try:
        result = await get_gateway().health()
    except Exception as exc:  # noqa: BLE001
        result = {"available": False, "provider": "error", "use_mock": False, "error": str(exc)}
    return ok(result)


# ---------- 分模型运行时配置（对话 / 向量 / 重排） ----------

_RAG_SERVICE_FIELDS = {
    "embedding": {
        "backend": "embedding_backend",
        "model": "embedding_model",
        "base_url": "embedding_base_url",
        "api_key": "embedding_api_key",
    },
    "reranker": {
        "backend": "reranker_backend",
        "model": "reranker_model",
        "base_url": "reranker_base_url",
        "api_key": "reranker_api_key",
    },
}

_RAG_SERVICE_LABELS = {
    "embedding_backend": "向量模型后端 (api / local)",
    "embedding_model": "向量模型标识（如 BAAI/bge-m3）",
    "embedding_base_url": "向量服务 Base URL",
    "embedding_api_key": "向量服务 API Key（敏感字段，明文存储）",
    "reranker_backend": "重排模型后端 (api / local)",
    "reranker_model": "重排模型标识（如 BAAI/bge-reranker-base）",
    "reranker_base_url": "重排服务 Base URL",
    "reranker_api_key": "重排服务 API Key（敏感字段，明文存储）",
}


class RagModelConfigBody(BaseModel):
    backend: str | None = Field(None, max_length=16)
    model: str | None = Field(None, max_length=128)
    base_url: str | None = Field(None, max_length=512)
    api_key: str | None = Field(None, max_length=2048)


def _rag_effective(settings, db_map: dict, field_map: dict, field: str):
    db_key = field_map[field]
    row = db_map.get(db_key)
    if row and row.value != "":
        return row.value
    return getattr(settings, db_key)


@router.get("/model-config", summary="按模型查看当前生效配置（对话 / 向量 / 重排）")
async def get_model_config(user: AdminUser, session: DBSession) -> dict:
    del user
    from app.core.config import get_settings
    from app.models.admin import SystemSetting

    settings = get_settings()
    rows = (await session.scalars(select(SystemSetting))).all()
    by_category: dict[str, dict[str, SystemSetting]] = {}
    for row in rows:
        by_category.setdefault(row.category, {})[row.key] = row

    chat_db = by_category.get("llm", {})
    chat_api_key = str(
        (chat_db.get("llm_api_key").value if chat_db.get("llm_api_key") and chat_db["llm_api_key"].value != "" else None)
        or settings.bailian_api_key
        or ""
    )
    use_mock = str(
        (chat_db.get("llm_use_mock").value if chat_db.get("llm_use_mock") and chat_db["llm_use_mock"].value != "" else None)
        or settings.llm_use_mock
    ).lower() in ("1", "true", "yes")
    chat = {
        "provider": "mock" if (use_mock or not chat_api_key) else "bailian",
        "model": str(_rag_effective(settings, chat_db, _LLM_KEY_MAP, "model")),
        "base_url": str(_rag_effective(settings, chat_db, _LLM_KEY_MAP, "base_url")),
        "api_key_masked": _mask_api_key(chat_api_key),
        "api_key_configured": bool(chat_api_key),
        "temperature": float(_rag_effective(settings, chat_db, _LLM_KEY_MAP, "temperature")),
        "timeout": int(_rag_effective(settings, chat_db, _LLM_KEY_MAP, "timeout")),
        "max_retries": int(_rag_effective(settings, chat_db, _LLM_KEY_MAP, "max_retries")),
        "use_mock": use_mock,
    }

    def rag_section(service: str) -> dict:
        field_map = _RAG_SERVICE_FIELDS[service]
        db_map = by_category.get(service, {})
        backend = str(_rag_effective(settings, db_map, field_map, "backend") or "local")
        api_key = str(_rag_effective(settings, db_map, field_map, "api_key") or "")
        return {
            "backend": backend,
            "model": str(_rag_effective(settings, db_map, field_map, "model")),
            "base_url": str(_rag_effective(settings, db_map, field_map, "base_url")),
            "api_key_masked": _mask_api_key(api_key),
            "api_key_configured": bool(api_key or settings.bailian_api_key),
            "has_db_override": bool(db_map),
        }

    return ok(
        {
            "chat": chat,
            "embedding": rag_section("embedding"),
            "reranker": rag_section("reranker"),
        }
    )


@router.put("/model-config/chat", summary="保存对话模型配置（即时生效）")
async def update_chat_model_config(
    body: LlmConfigUpdateBody,
    user: AdminUser,
    session: DBSession,
) -> dict:
    return await update_llm_config(body, user, session)


@router.put("/model-config/{service}", summary="保存向量/重排模型配置（下次调用生效）")
async def update_rag_model_config(
    service: str,
    body: RagModelConfigBody,
    user: AdminUser,
    session: DBSession,
) -> dict:
    if service not in _RAG_SERVICE_FIELDS:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未知模型服务")
    field_map = _RAG_SERVICE_FIELDS[service]
    payload = body.model_dump(exclude_unset=True)
    if not payload:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="未提供任何配置项")
    if payload.get("backend") is not None and payload["backend"] not in ("api", "local"):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail="backend 仅支持 api / local")
    from app.models.admin import SystemSetting
    from app.rag.runtime import refresh_runtime_rag_config

    actor_id = int(user["user_id"])
    saved: dict[str, str] = {}
    for field_name, value in payload.items():
        db_key = field_map[field_name]
        str_value = "" if value is None else str(value)
        existing = await session.scalar(select(SystemSetting).where(SystemSetting.key == db_key))
        if existing is None:
            existing = SystemSetting(key=db_key, category=service, description=_RAG_SERVICE_LABELS.get(db_key, ""))
            session.add(existing)
        existing.value = str_value
        existing.version = int(getattr(existing, "version", 1) or 1) + 1
        existing.updated_by = actor_id
        saved[field_name] = _mask_api_key(str_value) if field_name == "api_key" else str_value
    await session.flush()
    await audit(session, actor_id, "model_config.update", "system_setting", service, saved)
    await refresh_runtime_rag_config(session)
    await session.commit()
    return ok({"saved": saved, "notice": "配置已保存，向量/重排服务将在下一次调用时按新配置重建"})


@router.post("/model-config/{service}/test", summary="对单个模型服务执行连通性测试")
async def test_model_config(service: str, user: AdminUser, session: DBSession) -> dict:
    del user, session
    import time

    started = time.monotonic()
    if service == "chat":
        from app.llm.gateway import get_gateway

        try:
            result = await get_gateway().health()
            return ok({**result, "elapsed_ms": int((time.monotonic() - started) * 1000)})
        except Exception as exc:  # noqa: BLE001
            return ok({"available": False, "error": str(exc), "elapsed_ms": int((time.monotonic() - started) * 1000)})

    if service == "embedding":
        from app.rag.embedding import get_embedding_service

        try:
            vectors = await get_embedding_service().embed_query("油气储运模型连通性测试")
            return ok({
                "available": bool(vectors),
                "backend": get_embedding_service().backend,
                "dimension": len(vectors) if vectors else 0,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })
        except Exception as exc:  # noqa: BLE001
            return ok({"available": False, "error": str(exc), "elapsed_ms": int((time.monotonic() - started) * 1000)})

    if service == "reranker":
        from app.rag.reranker import get_reranker

        try:
            scores = await get_reranker().rerank("管道运行", ["油气管道运行安全", "课堂教学设计"])
            return ok({
                "available": bool(scores),
                "backend": get_reranker().backend,
                "elapsed_ms": int((time.monotonic() - started) * 1000),
            })
        except Exception as exc:  # noqa: BLE001
            return ok({"available": False, "error": str(exc), "elapsed_ms": int((time.monotonic() - started) * 1000)})

    raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="未知模型服务")
