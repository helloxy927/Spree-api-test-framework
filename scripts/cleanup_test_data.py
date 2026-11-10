"""清理测试产生的数据。

为什么需要它：订单、支付、购物车、地址会随着每次执行累积。验收要求「连续两周定时执行，
无非用例本身原因的失败残留」，数据不清理，第 3 天开始就会出现：
- 订单列表分页把新单挤到第 2 页，断言莫名失败；
- 商品库存被测试订单占满，正常下单变 422；
- 数据库里堆几千条垃圾数据，查问题无从下手。

清理策略：用例建购物车时会写入 `customer_note = qa:<RUN_ID>`，订单会继承这个标记，
所以可以按前缀精确删除，不碰真实业务数据。

用法：
    python scripts/cleanup_test_data.py            # 只统计，不删除
    python scripts/cleanup_test_data.py --yes      # 删除带 qa: 标记的数据
    python scripts/cleanup_test_data.py --all --yes  # 连同历史遗留（无标记）一起清空
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from framework.config import get_settings  # noqa: E402
from framework.db import Database  # noqa: E402

TAG = "qa:%"
QA_EMAIL = "email like 'qa\\_%'"

# 删除顺序：先子表后主表，否则外键会拦
CASCADE = [
    (
        "支付（按订单）",
        "delete from spree_payments where order_id in "
        "(select id from spree_orders where customer_note like :tag)",
    ),
    (
        "订单明细（按订单）",
        "delete from spree_line_items where order_id in "
        "(select id from spree_orders where customer_note like :tag)",
    ),
    (
        "履约单（按订单）",
        "delete from spree_fulfillments where order_id in "
        "(select id from spree_orders where customer_note like :tag)",
    ),
    ("订单", "delete from spree_orders where customer_note like :tag"),
    (
        "支付（按购物车）",
        "delete from spree_payments where cart_id in "
        "(select id from spree_carts where customer_note like :tag)",
    ),
    (
        "购物车明细",
        "delete from spree_line_items where cart_id in "
        "(select id from spree_carts where customer_note like :tag)",
    ),
    ("购物车", "delete from spree_carts where customer_note like :tag"),
    (
        "孤儿地址（不被订单/购物车引用）",
        "delete from spree_addresses a where not exists "
        "(select 1 from spree_orders o where o.bill_address_id = a.id or o.ship_address_id = a.id) "
        "and not exists "
        "(select 1 from spree_carts c where c.bill_address_id = a.id or c.ship_address_id = a.id)",
    ),
    (
        "测试顾客的地址",
        "delete from spree_addresses where owner_type = 'Spree::Customer' and owner_id in "
        "(select id from spree_customers where email like 'qa\\_%')",
    ),
    ("测试顾客", "delete from spree_customers where email like 'qa\\_%'"),
]

LEGACY = [
    ("【历史】全部支付", "delete from spree_payments"),
    ("【历史】全部明细", "delete from spree_line_items"),
    ("【历史】全部履约单", "delete from spree_fulfillments"),
    ("【历史】全部订单", "delete from spree_orders"),
    ("【历史】全部购物车", "delete from spree_carts"),
    ("【历史】全部地址", "delete from spree_addresses"),
]


def count_of(db: Database, table: str, where: str = "true", **params) -> int:
    try:
        return db.scalar(f"select count(*) from {table} where {where}", **params)
    except Exception:
        return -1


def main() -> int:
    parser = argparse.ArgumentParser(description="清理接口自动化测试产生的数据")
    parser.add_argument("--yes", action="store_true", help="真正执行删除（默认只统计）")
    parser.add_argument("--all", action="store_true", help="连同历史遗留数据一起清空")
    args = parser.parse_args()

    settings = get_settings()
    db = Database(settings.db_dsn)

    print("=== 清理前 ===")
    print(f"订单(qa 标记)   : {count_of(db, 'spree_orders', 'customer_note like :tag', tag=TAG)}")
    print(f"订单(全部)      : {count_of(db, 'spree_orders')}")
    print(f"购物车(全部)    : {count_of(db, 'spree_carts')}")
    print(f"支付(全部)      : {count_of(db, 'spree_payments')}")
    print(f"明细(全部)      : {count_of(db, 'spree_line_items')}")
    print(f"顾客地址(全部)  : {count_of(db, 'spree_addresses')}")
    print(f"测试顾客(qa_)   : {count_of(db, 'spree_customers', QA_EMAIL)}")

    steps = list(CASCADE) + (list(LEGACY) if args.all else [])

    if not args.yes:
        print("\n[dry-run] 未删除任何数据。加 --yes 执行。")
        for name, _ in steps:
            print(f"  将执行: {name}")
        db.close()
        return 0

    print("\n=== 开始清理 ===")
    failures = 0
    for name, sql in steps:
        try:
            affected = db.execute(sql, tag=TAG) if ":tag" in sql else db.execute(sql)
            print(f"{name:<18} 删除 {affected} 行")
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"{name:<18} 失败: {str(exc).splitlines()[0][:120]}")

    print("\n=== 清理后 ===")
    print(f"订单(全部)      : {count_of(db, 'spree_orders')}")
    print(f"购物车(全部)    : {count_of(db, 'spree_carts')}")
    print(f"支付(全部)      : {count_of(db, 'spree_payments')}")
    print(f"明细(全部)      : {count_of(db, 'spree_line_items')}")
    print(f"顾客地址(全部)  : {count_of(db, 'spree_addresses')}")
    print(f"测试顾客(qa_)   : {count_of(db, 'spree_customers', QA_EMAIL)}")

    db.close()
    print("\n结果:", "完成" if failures == 0 else f"完成，但有 {failures} 步失败，请人工确认")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
