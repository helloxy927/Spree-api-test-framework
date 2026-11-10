"""数据库访问层，专门服务第三层断言。

只做两件事：查（校验状态是否真的落库）、等（等异步流程最终一致）。
业务逻辑不要写在这里，用例里看到的是 SQL + 期望值，这样 review 时一眼能懂。
"""

from __future__ import annotations

import time
from typing import Any, Callable

from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine


class Database:
    def __init__(self, dsn: str) -> None:
        self.engine: Engine = create_engine(dsn, pool_pre_ping=True, future=True)

    # ---------------- 查询 ----------------
    def fetch_all(self, sql: str, **params: Any) -> list[dict[str, Any]]:
        with self.engine.connect() as conn:
            rows = conn.execute(text(sql), params).mappings().all()
            return [dict(row) for row in rows]

    def fetch_one(self, sql: str, **params: Any) -> dict[str, Any] | None:
        rows = self.fetch_all(sql, **params)
        return rows[0] if rows else None

    def scalar(self, sql: str, **params: Any) -> Any:
        row = self.fetch_one(sql, **params)
        return next(iter(row.values())) if row else None

    def execute(self, sql: str, **params: Any) -> int:
        with self.engine.begin() as conn:
            return conn.execute(text(sql), params).rowcount

    # ---------------- 等待 ----------------
    def wait_until(
        self,
        check: Callable[[], bool],
        timeout: float = 15.0,
        interval: float = 0.5,
        message: str = "",
    ) -> None:
        """轮询等待最终一致（支付回调落库、订单状态流转都靠它）。"""
        deadline = time.time() + timeout
        last_error: Exception | None = None
        while time.time() < deadline:
            try:
                if check():
                    return
            except Exception as exc:  # noqa: BLE001 - 轮询期间任何异常都先记下
                last_error = exc
            time.sleep(interval)
        raise AssertionError(message or f"等待 {timeout}s 仍未满足条件") from last_error

    def close(self) -> None:
        self.engine.dispose()
