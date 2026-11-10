"""把 Spree 示例数据修正成「Store API 可见」的状态，幂等可重复执行。

背景：`spree sample-data` 灌进去的商品默认对 Storefront API 不可见，原因是
1) 没有 products <-> stores 关联；2) product_publications.published_at 为空；
3) available_on 为空；4) 店铺币种下只有 price_list 价格、没有基价。

用法：
    python scripts/prepare_sut.py

任何一步失败都会打印原因但不中断后续步骤，最后打印汇总。
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from framework.client import ApiClient  # noqa: E402
from framework.config import get_settings  # noqa: E402
from framework.db import Database  # noqa: E402

STEPS: list[tuple[str, str]] = []


def run_step(name: str, sql: str, db: Database) -> None:
    try:
        affected = db.execute(sql)
        STEPS.append((name, f"OK ({affected} 行)"))
    except Exception as exc:  # noqa: BLE001
        STEPS.append((name, f"SKIP/ERR: {str(exc).splitlines()[0][:100]}"))


def ensure_demo_customer(api: ApiClient, settings) -> None:
    resp = api.post(
        "/api/v3/store/customers",
        json={
            "email": settings.customer_email,
            "password": settings.customer_password,
            "password_confirmation": settings.customer_password,
            "first_name": "QA",
            "last_name": "Bot",
        },
    )
    if resp.status_code in (200, 201):
        STEPS.append(("创建测试顾客", "OK (新建)"))
    elif resp.status_code == 422:
        STEPS.append(("创建测试顾客", "OK (已存在)"))
    else:
        STEPS.append(("创建测试顾客", f"ERR {resp.status_code} {resp.text[:80]}"))


def main() -> int:
    settings = get_settings()
    db = Database(settings.db_dsn)

    # 1) 商品必须挂在店铺上（Store API 走 store.products）
    run_step(
        "关联 products <-> stores",
        "insert into spree_products_stores (product_id, store_id, created_at, updated_at) "
        "select p.id, p.store_id, now(), now() from spree_products p "
        "where p.deleted_at is null "
        "  and not exists (select 1 from spree_products_stores ps "
        "                  where ps.product_id = p.id and ps.store_id = p.store_id)",
        db,
    )

    # 2) 上架时间：available_on 为空会被 available 过滤掉
    run_step(
        "补齐 available_on",
        "update spree_products set available_on = now() "
        "where available_on is null and deleted_at is null",
        db,
    )

    # 3) 发布到所有 channel
    run_step(
        "发布商品到 channel",
        "update spree_product_publications set published_at = now() "
        "where published_at is null and unpublished_at is null",
        db,
    )

    # 4) 店铺币种下的基价：示例数据的 CNY 价格全挂在 price_list 上，
    #    available 只认 price_list_id IS NULL 的基价，缺了整店商品就不可见
    run_step(
        "补齐店铺币种基价",
        "insert into spree_prices (variant_id, currency, amount, price_list_id, created_at, updated_at) "
        "select v.id, s.default_currency, pr.amount, null, now(), now() "
        "from spree_stores s "
        "join spree_products p on p.store_id = s.id and p.deleted_at is null "
        "join spree_variants v on v.product_id = p.id and v.deleted_at is null "
        "join spree_prices pr on pr.variant_id = v.id and pr.price_list_id is null "
        "     and pr.deleted_at is null and pr.currency <> s.default_currency "
        "where not exists (select 1 from spree_prices p2 where p2.variant_id = v.id "
        "                  and p2.currency = s.default_currency and p2.price_list_id is null)",
        db,
    )

    # 5) 清 Rails 缓存，避免旧结果残留
    run_step("清理 solid_cache", "delete from solid_cache_entries", db)

    api = ApiClient(settings)
    ensure_demo_customer(api, settings)

    resp = api.get("/api/v3/store/products", params={"per_page": 1})
    count = resp.json().get("meta", {}).get("count") if resp.status_code == 200 else "?"
    STEPS.append(("Store API 商品数", str(count)))
    api.close()
    db.close()

    width = max(len(name) for name, _ in STEPS) + 2
    print("\n=== SUT 数据准备 ===")
    for name, result in STEPS:
        print(f"{name:<{width}} {result}")

    ok = count not in (0, "?", None)
    print("\n结果:", "可用" if ok else "仍不可见，请检查上面的失败步骤")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
