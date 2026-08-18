"""集成测试公共夹具：建表 + 种子数据 + ASGI 客户端。"""

from __future__ import annotations

import asyncio
import os

# 集成测试环境：SQLite + Mock
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test_integration.db")
os.environ.setdefault("LLM_USE_MOCK", "true")
os.environ.setdefault("BAILIAN_API_KEY", "")

import httpx  # noqa: E402
import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402

from app.db.session import AsyncSessionLocal, Base, engine  # noqa: E402
from app.llm import reset_gateway  # noqa: E402
from app.rag import reset_pipeline  # noqa: E402
from app.rag.store import reset_vector_store  # noqa: E402
from app.workflow.factory import reset_engines  # noqa: E402


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _bootstrap_db():
    """建表 + 种子（整会话一次）。"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    from app.seed import seed

    await seed(reset=True)
    yield
    # 清理
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client():
    """每个测试一个干净客户端 + 重置单例。"""
    await reset_gateway()
    reset_pipeline()
    reset_vector_store()
    reset_engines()
    app = __import__("app.main", fromlist=["create_app"]).create_app()
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://t") as c:
        yield c


@pytest_asyncio.fixture
async def student_token(client):
    """登录学生并返回 Authorization 头。"""
    r = await client.post(
        "/api/auth/login",
        json={"username": "student", "password": "student123"},
    )
    assert r.status_code == 200
    token = r.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def teacher_token(client):
    """登录教师并返回 Authorization 头。"""
    r = await client.post(
        "/api/auth/login",
        json={"username": "teacher", "password": "teacher123"},
    )
    assert r.status_code == 200
    token = r.json()["data"]["token"]
    return {"Authorization": f"Bearer {token}"}


@pytest_asyncio.fixture
async def admin_token(client):
    """登录管理员并返回 Authorization 头。"""
    r = await client.post(
        "/api/auth/login",
        json={"username": "admin", "password": "admin123"},
    )
    assert r.status_code == 200
    return {"Authorization": f"Bearer {r.json()['data']['token']}"}
