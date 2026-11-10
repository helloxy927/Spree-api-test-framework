"""测试数据工厂：唯一化 + 登记 + 兜底清理。

三个设计要点（面试必问）：
1. 所有数据带 RUN_ID 前缀 —— 每次运行、每个并行 worker 天然隔离，重跑不撞唯一索引；
2. 谁创建谁登记，teardown 逆序删除 —— 用例之间没有顺序依赖；
3. 清理失败只记录不抛异常 —— 清理不能反过来把用例搞挂，但必须留下痕迹。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from typing import Any


@dataclass
class CreatedRecord:
    table: str
    pk: str
    value: Any


class DataFactory:
    def __init__(self, run_id: str) -> None:
        self.run_id = run_id
        self.created: list[CreatedRecord] = []

    # ---------------- 造数据 ----------------
    def unique(self, tag: str) -> str:
        return f"qa_{self.run_id}_{tag}_{uuid.uuid4().hex[:6]}"

    def email(self, tag: str = "customer") -> str:
        return f"{self.unique(tag)}@example.test"

    def customer_payload(
        self,
        *,
        email: str | None = None,
        password: str = "Passw0rd!",
        first_name: str = "QA",
        last_name: str = "Bot",
    ) -> dict[str, str]:
        return {
            "email": email or self.email("customer"),
            "password": password,
            "password_confirmation": password,
            "first_name": first_name,
            "last_name": last_name,
        }

    # ---------------- 登记与清理 ----------------
    def record(self, table: str, pk: str, value: Any) -> None:
        """登记一条需要清理的记录。table/pk 必须是代码里的常量，不能来自用户输入。"""
        self.created.append(CreatedRecord(table=table, pk=pk, value=value))

    def cleanup(self, db: Any) -> list[str]:
        """逆序删除已登记的数据，返回清理失败的记录（不抛异常）。"""
        problems: list[str] = []
        for item in reversed(self.created):
            try:
                db.execute(f"DELETE FROM {item.table} WHERE {item.pk} = :value", value=item.value)
            except Exception as exc:  # noqa: BLE001 - 清理失败只记录
                problems.append(f"{item.table}({item.pk}={item.value}): {exc}")
        self.created.clear()
        return problems
