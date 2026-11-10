"""环境配置：所有可变项都从环境变量读取，本地 .env 与 CI secrets 共用同一套键名。

为什么要集中在这里：
- 用例里不出现任何魔法值，换环境只改 .env / secrets；
- RUN_ID 贯穿「数据隔离 + 清理」，是两周期稳定跑的核心；
- 缺少必需变量时立刻报错，而不是跑一半才发现。
"""

from __future__ import annotations

import os
import uuid
from dataclasses import dataclass
from datetime import datetime
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent

# override=False：已经存在的环境变量（CI 注入）优先于 .env
load_dotenv(ROOT / ".env", override=False)


def _env(name: str, default: str = "", required: bool = False) -> str:
    value = (os.getenv(name) or default).strip()
    if required and not value:
        raise RuntimeError(
            f"缺少环境变量 {name}。请复制 .env.example 为 .env 并填写完整，"
            f"或在 CI 中配置同名 secret。"
        )
    return value


def _build_run_id() -> str:
    fixed = _env("RUN_ID")
    if fixed:
        return fixed
    return f"{datetime.now():%m%d%H%M%S}-{uuid.uuid4().hex[:4]}"


@dataclass(frozen=True)
class Settings:
    base_url: str
    api_key: str
    customer_email: str
    customer_password: str
    db_dsn: str
    timeout: int
    retries: int
    run_id: str
    attach_all: bool

    @property
    def store_api(self) -> str:
        return f"{self.base_url}/api/v3/store"

    @property
    def admin_api(self) -> str:
        return f"{self.base_url}/api/v3/admin"


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings(
        base_url=_env("BASE_URL", "http://localhost:3000").rstrip("/"),
        api_key=_env("API_KEY", required=True),
        customer_email=_env("CUSTOMER_EMAIL", "customer@example.com"),
        customer_password=_env("CUSTOMER_PASSWORD", "password123"),
        db_dsn=_env("DB_DSN"),
        timeout=int(_env("TIMEOUT", "30")),
        retries=int(_env("RETRIES", "2")),
        run_id=_build_run_id(),
        attach_all=_env("ATTACH_ALL", "1") == "1",
    )
