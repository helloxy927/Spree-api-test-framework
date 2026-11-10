"""启动自检：环境变量 / SUT 连通性 / 数据库连通性。

用法：
    python scripts/check_env.py

任何一项不通过都会给出可执行的修复提示，避免「跑一半才发现 .env 没配」。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from framework.client import ApiClient  # noqa: E402
from framework.config import get_settings  # noqa: E402
from framework.db import Database  # noqa: E402


def main() -> int:
    ok = True
    settings = get_settings()

    print(f"BASE_URL : {settings.base_url}")
    print(f"RUN_ID   : {settings.run_id}")
    print(f"API_KEY  : {settings.api_key[:6]}***")

    client = ApiClient(settings)
    try:
        resp = client.get("/api/v3/store/products")
        elapsed = getattr(resp, "elapsed_ms", 0)
        print(f"[HTTP] GET /api/v3/store/products -> {resp.status_code} ({elapsed} ms)")
        if resp.status_code != 200:
            ok = False
            print(f"       响应: {resp.text[:300]}")
    except Exception as exc:  # noqa: BLE001
        ok = False
        print(f"[HTTP] 连接失败: {exc}")
        print("       检查 Spree 是否已启动：docker compose ps / curl http://localhost:3000")
    finally:
        client.close()

    if settings.db_dsn:
        try:
            database = Database(settings.db_dsn)
            print(f"[DB]   SELECT 1 -> {database.scalar('SELECT 1')}")
            database.close()
        except Exception as exc:  # noqa: BLE001
            ok = False
            print(f"[DB]   连接失败: {exc}")
    else:
        print("[DB]   未配置 DB_DSN，数据库校验相关用例会被跳过")

    print("\n结果:", "全部通过" if ok else "存在问题，请按上面的提示修正")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
