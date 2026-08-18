"""pytest 全局配置。"""

from __future__ import annotations

import os

# 测试环境：默认 SQLite + Mock，避免依赖外部服务
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./test.db")
os.environ.setdefault("LLM_USE_MOCK", "true")
os.environ.setdefault("BAILIAN_API_KEY", "")
