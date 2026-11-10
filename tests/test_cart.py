"""购物车（9 条，正常 6 / 异常 3）。

游客购物车用 `X-Spree-Token` 鉴权，和 JWT 是两套体系 —— 这也是「订单 token 只授权一个购物车」的
安全设计，用例里专门验证了「没有 token 拿不到车」。
"""

from __future__ import annotations

from decimal import Decimal

import allure
import pytest

from framework import assertions as expect

STORE = "/api/v3/store"
pytestmark = [pytest.mark.cart]


def _db_quantity(db, token: str) -> int:
    return db.scalar(
        "select coalesce(sum(li.quantity), 0) from spree_line_items li "
        "join spree_carts c on c.id = li.cart_id where c.token = :t",
        t=token,
    )


@allure.feature("购物车")
class TestCart:
    @allure.story("创建购物车")
    @pytest.mark.db
    def test_create_cart_persists(self, api, db, settings):
        from tests.helpers import GuestCart

        cart = GuestCart.create(api, settings)
        try:
            row = db.fetch_one(
                "select id, currency from spree_carts where token = :t", t=cart.token
            )
            assert row, "购物车没有落库"
            assert row["currency"] == "CNY"
        finally:
            cart.destroy()

    @allure.story("加购落库")
    @pytest.mark.db
    def test_add_item_persists_line_item(self, guest_cart, db, product_variant):
        variant = product_variant["variant"]
        resp = guest_cart.add(variant["id"], 2)
        assert resp.status_code in (200, 201), f"加购失败: {resp.status_code} {resp.text[:200]}"

        items = guest_cart.items()
        assert len(items) == 1
        assert items[0]["quantity"] == 2
        assert _db_quantity(db, guest_cart.token) == 2

    @allure.story("重复加购合并数量")
    def test_add_same_variant_twice_merges(self, guest_cart, product_variant):
        vid = product_variant["variant"]["id"]
        guest_cart.add(vid, 1)
        guest_cart.add(vid, 2)

        items = guest_cart.items()
        assert len(items) == 1, f"同一 variant 应合并为一行，实际 {len(items)} 行"
        assert items[0]["quantity"] == 3

    @allure.story("修改数量")
    def test_update_quantity(self, guest_cart, product_variant):
        guest_cart.add(product_variant["variant"]["id"], 1)
        item = guest_cart.items()[0]

        resp = guest_cart.update(item["id"], 4)
        assert resp.status_code == 200, f"改数量失败: {resp.status_code} {resp.text[:200]}"
        assert guest_cart.items()[0]["quantity"] == 4

    @allure.story("删除商品")
    @pytest.mark.db
    def test_remove_item(self, guest_cart, db, product_variant):
        guest_cart.add(product_variant["variant"]["id"], 1)
        item = guest_cart.items()[0]

        resp = guest_cart.remove(item["id"])
        assert resp.status_code in (200, 204)
        assert guest_cart.items() == []
        expect.assert_db_value(
            db,
            "select count(*) from spree_line_items li "
            "join spree_carts c on c.id = li.cart_id where c.token = :t",
            0,
            t=guest_cart.token,
        )

    @allure.story("金额 = 单价 × 数量")
    def test_total_equals_price_times_quantity(self, guest_cart, product_variant):
        guest_cart.add(product_variant["variant"]["id"], 3)
        item = guest_cart.items()[0]

        expected = Decimal(str(item["price"])) * 3
        assert Decimal(str(guest_cart.total())) == expected, (
            f"购物车金额不对: total={guest_cart.total()} 期望 {expected}"
        )

    @allure.story("不存在的 variant")
    def test_add_unknown_variant(self, guest_cart):
        resp = guest_cart.add("variant_does_not_exist", 1)
        expect.assert_business_error(resp, http_status=404)

    @allure.story("多种商品金额累加")
    def test_two_variants_total_is_sum(self, guest_cart, api, product_variant):
        detail = api.get(
            f"{STORE}/products/{product_variant['product']['slug']}", params={"expand": "variants"}
        ).json()
        variants = detail["variants"][:2]
        for variant in variants:
            guest_cart.add(variant["id"], 1)

        items = guest_cart.items()
        assert len(items) == len(variants), f"应有两行明细，实际 {len(items)}"
        expected = sum(Decimal(str(i["price"])) * i["quantity"] for i in items)
        assert Decimal(str(guest_cart.total())) == expected
