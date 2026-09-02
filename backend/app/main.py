"""油训智安 OilTrainSafe — FastAPI 应用入口。

启动：uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any, AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api import ok
from app.api.routers import health
from app.core.config import get_settings
from app.core.logging import logger, setup_logging

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """应用生命周期：启动/关闭钩子。"""
    setup_logging()
    logger.info("启动 {} (env={}, port={})", settings.app_name, settings.app_env, settings.app_port)
    logger.info("LLM 模式: {}", "mock" if not settings.llm_available else f"bailian({settings.bailian_model})")
    # 从 DB 加载运行时 LLM 配置（优先级高于 .env）
    try:
        from app.db.session import AsyncSessionLocal
        from app.llm.gateway import refresh_runtime_llm_config

        async with AsyncSessionLocal() as session:
            await refresh_runtime_llm_config(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("运行时 LLM 配置启动加载失败，使用 .env：{}", exc)
    # 从 DB 加载向量/重排模型运行时配置（优先级高于 .env）
    try:
        from app.db.session import AsyncSessionLocal
        from app.rag.runtime import refresh_runtime_rag_config

        async with AsyncSessionLocal() as session:
            await refresh_runtime_rag_config(session)
    except Exception as exc:  # noqa: BLE001
        logger.warning("RAG 运行时配置启动加载失败，使用 .env：{}", exc)
    # 采集任务重启恢复：把上次进程中断留下的 queued/running 任务明确标记为失败
    try:
        from app.api.routers.position_admin import fail_stale_discovery_runs

        recovered = await fail_stale_discovery_runs()
        if recovered:
            logger.warning("启动恢复：{} 个遗留采集任务已标记为失败", recovered)
    except Exception as exc:  # noqa: BLE001
        logger.warning("启动采集任务恢复检查失败：{}", exc)
    yield
    logger.info("应用关闭")


def create_app() -> FastAPI:
    app = FastAPI(
        title=settings.app_name,
        description="油气储运工程岗位智能实训与安全能力评测系统 API",
        version="0.1.0",
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---- 异常处理 ----
    from app.api.response import AppError, app_error_handler, unhandled_exception_handler

    app.add_exception_handler(AppError, app_error_handler)
    app.add_exception_handler(Exception, unhandled_exception_handler)

    # ---- 路由 ----
    app.include_router(health.router, prefix="/api")

    # 业务路由在后续 Phase 逐步挂载
    _register_business_routers(app)

    @app.get("/api", include_in_schema=False)
    async def root() -> dict[str, Any]:
        return ok({"name": settings.app_name, "version": "0.1.0", "status": "running"})

    return app


def _register_business_routers(app: FastAPI) -> None:
    """按可用性挂载业务路由（避免未完成模块阻断启动）。"""
    _try_include(app, "app.api.routers.auth", "auth")
    _try_include(app, "app.api.routers.positions", "positions")
    # 仿真路由必须先于 training 注册：training 的 GET /{session_id} 会遮蔽 /training/simulation 列表路径
    _try_include(app, "app.api.routers.training_simulation", "training_simulation")
    _try_include(app, "app.api.routers.training", "training")
    _try_include(app, "app.api.routers.chat", "chat")
    _try_include(app, "app.api.routers.ability", "ability")
    _try_include(app, "app.api.routers.recommendation", "recommendation")
    _try_include(app, "app.api.routers.teacher", "teacher")
    _try_include(app, "app.api.routers.position_admin", "position_admin")
    _try_include(app, "app.api.routers.knowledge", "knowledge")
    _try_include(app, "app.api.routers.prompt_admin", "prompt_admin")
    _try_include(app, "app.api.routers.program_admin", "program_admin")
    _try_include(app, "app.api.routers.professional_group", "professional_group")
    _try_include(app, "app.api.routers.analytics_ext", "analytics_ext")
    _try_include(app, "app.api.routers.competition", "competition")
    _try_include(app, "app.api.routers.admin", "admin")


def _try_include(app: FastAPI, module: str, name: str) -> None:
    try:
        import importlib

        mod = importlib.import_module(module)
        if hasattr(mod, "router"):
            app.include_router(getattr(mod, "router"), prefix="/api")  # type: ignore[arg-type]
            logger.info("路由 {} 已加载", name)
        else:
            logger.warning("路由 {} 没有 router 属性", name)
    except Exception as exc:  # noqa: BLE001
        logger.error("路由 {} 加载失败: {} - {}", name, type(exc).__name__, exc)


app = create_app()
