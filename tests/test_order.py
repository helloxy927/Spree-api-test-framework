"""订单（12 条，正常 8 / 异常 4）。

一张订单要穿过「地址 → 运费 → 支付 → 完成」四个状态，任何一层没落库，
接口都可能返回 200。所以这里每条关键用例都做数据库核对。
"""

from __future__ import annotations

import re
from decimal import Decimal

import allure
import pytest

from framework import assertions as expect
from tests.helpers import Checkout

STORE = "/api/v3/store"
pytestmark = [pytest.mark.order]


def _db_order(db, number: str) -> dict:
    row = db.fetch_one("select * from spree_orders where number = :n", n=number)
    assert row, f"数据库里没有订单 {number}"
    return row


@allure.feature("订单")
class TestOrderCreation:
    @allure.story("下单成功")
    def test_complete_cart_returns_order(self, order, settings):
        body = order["body"]
        assert re.match(r"^R\d+$", body["number"]), f"订单号格式不对: {body['number']}"
        # 已登录顾客下单时，订单邮箱取账号邮箱，而不是购物车上临时填的
        assert body["email"] == settings.customer_email
        assert Decimal(str(body["total"])) > 0

    @allure.story("订单落库")
    @pytest.mark.db
    def test_order_persisted(self, order, db, settings):
        body = order["body"]
        row = _db_order(db, body["number"])
        assert row["completed_at"] is not None
        assert row["email"] == settings.customer_email
        assert Decimal(str(row["total"])) == Decimal(str(body["total"]))

    @allure.story("金额构成正确")
    @pytest.mark.db
    def test_total_equals_item_plus_delivery(self, order, db):
        row = _db_order(db, order["body"]["number"])
        expected = (
            Decimal(str(row["item_total"]))
            + Decimal(str(row["delivery_total"]))
            + Decimal(str(row["additional_tax_total"]))
            - Decimal(str(row["discount_total"]))
        )
        assert Decimal(str(row["total"])) == expected, (
            f"总额不等于 商品+运费+税-折扣: total={row['total']} 期望 {expected}"
        )

    @allure.story("明细数量正确")
    @pytest.mark.db
    def test_line_items_match(self, order, db):
        row = _db_order(db, order["body"]["number"])
        items = db.fetch_all("select * from spree_line_items where order_id = :o", o=row["id"])
        assert items, "订单没有明细"
        assert sum(i["quantity"] for i in items) == 1
        assert all(Decimal(str(i["price"])) > 0 for i in items)

    @allure.story("支付记录已生成")
    @pytest.mark.db
    def test_payment_recorded(self, order, db):
        row = _db_order(db, order["body"]["number"])
        payments = db.fetch_all("select * from spree_payments where order_id = :o", o=row["id"])
        assert payments, "订单没有支付记录"
        assert Decimal(str(payments[0]["amount"])) == Decimal(str(row["total"]))

    @allure.story("库存分配")
    @pytest.mark.db
    def test_stock_allocated(self, auth_api, db, factory, product_variant):
        sku = product_variant["variant"]["sku"]

        def allocated() -> int:
            return db.scalar(
                "select coalesce(sum(sl.allocated_count), 0) from spree_stock_levels sl "
                "join spree_variants v on v.id = sl.variant_id where v.sku = :s",
                s=sku,
            )

        before = allocated()
        checkout = Checkout(customer=auth_api, email=factory.email("buyer"))
        checkout.place_order(product_variant["variant"]["id"], 2)
        after = allocated()
        # 下单只做库存分配（allocated_count），真正扣减要等发货
        assert after >= before + 2, f"库存没有分配: before={before} after={after}"

    @allure.story("账户邮箱与订单一致")
    def test_order_email_matches_account(self, order, settings):
        expect.assert_fields(order["body"], email=settings.customer_email)


@allure.feature("订单")
class TestOrderQuery:
    @allure.story("我的订单列表包含新订单")
    def test_list_contains_new_order(self, order, auth_api):
        # 订单多了以后默认分页会把新单挤到后面，用 q[number_eq] 精确定位
        number = order["body"]["number"]
        body = expect.assert_business_ok(
            auth_api.get(f"{STORE}/customers/me/orders", params={"q[number_eq]": number})
        )
        assert body["meta"]["count"] == 1, f"订单列表里找不到 {number}"
        expect.assert_fields(body["data"][0], number=number)

    @allure.story("订单详情")
    def test_get_order_detail(self, order, auth_api):
        # v3 的订单详情按 prefixed id 查，传订单号（Rxxxx）是 404
        resp = auth_api.get(f"{STORE}/orders/{order['body']['id']}")
        body = expect.assert_business_ok(resp)
        expect.assert_fields(body, number=order["body"]["number"])

    @allure.story("别人的订单看不到")
    def test_other_customer_cannot_read_order(self, order, api, factory):
        other_email = factory.email("other")
        reg = api.post(
            f"{STORE}/customers",
            json={
                "email": other_email,
                "password": "Passw0rd!",
                "password_confirmation": "Passw0rd!",
                "first_name": "Other",
                "last_name": "User",
            },
        )
        assert reg.status_code in (200, 201)
        other_token = api.post(
            f"{STORE}/auth/login", json={"email": other_email, "password": "Passw0rd!"}
        ).json()["token"]
        from framework.client import ApiClient

        other = ApiClient(api.settings, token=other_token)
        try:
            resp = other.get(f"{STORE}/orders/{order['body']['id']}")
            assert resp.status_code in (401, 403, 404), f"越权读到了别人的订单: {resp.status_code}"
        finally:
            other.close()
            factory.record("spree_customers", "email", other_email)


@allure.feature("订单")
class TestOrderNegative:
    @allure.story("空车不能下单")
    def test_empty_cart_cannot_complete(self, auth_api):
        cart = auth_api.post(f"{STORE}/carts").json()
        resp = auth_api.post(
            f"{STORE}/carts/{cart['id']}/complete",
            headers={"X-Spree-Token": cart["token"]},
        )
        assert resp.status_code in (400, 422), f"空车下单返回了 {resp.status_code}"

    @allure.story("重复调用 complete 不产生第二张单")
    @pytest.mark.db
    def test_complete_twice_is_idempotent(self, order, db):
        checkout: Checkout = order["checkout"]
        second = checkout.complete()
        assert second.status_code in (200, 400, 404, 422)

        row = _db_order(db, order["body"]["number"])
        count = db.scalar("select count(*) from spree_orders where cart_id = :c", c=row["cart_id"])
        assert count == 1, f"同一购物车产生了 {count} 张订单"

    @allure.story("缺少支付方式不能下单")
    def test_cannot_complete_without_payment(self, auth_api, factory, product_variant):
        checkout = Checkout(customer=auth_api, email=factory.email("nopay"))
        checkout.add_item(product_variant["variant"]["id"], 1)
        checkout.attach_address()
        resp = checkout.complete()
        assert resp.status_code in (400, 422), f"未支付却下单成功: {resp.status_code}"

    @allure.story("多件商品订单金额")
    @pytest.mark.db
    def test_order_with_quantity_two(self, auth_api, db, factory, product_variant):
        checkout = Checkout(customer=auth_api, email=factory.email("buyer"))
        body = checkout.place_order(product_variant["variant"]["id"], 2)

        row = _db_order(db, body["number"])
        items = db.fetch_all("select * from spree_line_items where order_id = :o", o=row["id"])
        assert sum(i["quantity"] for i in items) == 2

        unit = Decimal(str(items[0]["price"]))
        delivery = Decimal(str(row["delivery_total"]))
        assert Decimal(str(body["item_total"])) == unit * 2
        assert Decimal(str(body["total"])) == unit * 2 + delivery
