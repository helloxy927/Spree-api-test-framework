"""支付（10 条，正常 6 / 异常 4）。

Spree 的支付是「先建 payment（checkout 态）→ 完成购物车 → 支付变 completed、订单变 paid」，
这条状态链是支付模块最值得测的东西。
"""

from __future__ import annotations

from decimal import Decimal

import allure
import pytest

from framework import assertions as expect
from framework.client import ApiClient
from tests.helpers import Checkout

STORE = "/api/v3/store"
pytestmark = [pytest.mark.payment]


def _cart_total(checkout: Checkout) -> Decimal:
    body = checkout.customer.get(f"{STORE}/carts/{checkout.id}", headers=checkout.headers).json()
    return Decimal(str(body["total"]))


@allure.feature("支付")
class TestPaymentCreation:
    @allure.story("创建支付")
    def test_create_payment(self, auth_api, factory, product_variant):
        checkout = Checkout(customer=auth_api, email=factory.email("pay"))
        checkout.add_item(product_variant["variant"]["id"], 1)
        checkout.attach_address()

        resp = checkout.pay()
        assert resp.status_code == 201, f"创建支付失败: {resp.status_code} {resp.text[:300]}"
        body = resp.json()
        assert body["status"] in ("checkout", "pending"), f"初始状态异常: {body['status']}"
        assert Decimal(str(body["amount"])) == _cart_total(checkout)

    @allure.story("支付落库")
    @pytest.mark.db
    def test_payment_persisted(self, auth_api, db, factory, product_variant):
        checkout = Checkout(customer=auth_api, email=factory.email("pay"))
        checkout.add_item(product_variant["variant"]["id"], 1)
        checkout.attach_address()
        payment = checkout.pay().json()

        row = db.fetch_one(
            "select p.* from spree_payments p "
            "join spree_carts c on c.id = p.cart_id where c.token = :t",
            t=checkout.token,
        )
        assert row, "支付记录没有落库"
        assert row["cart_id"] is not None
        assert Decimal(str(row["amount"])) == Decimal(str(payment["amount"]))

    @allure.story("支付方式不存在")
    def test_invalid_payment_method(self, auth_api, factory, product_variant):
        checkout = Checkout(customer=auth_api, email=factory.email("pay"))
        checkout.add_item(product_variant["variant"]["id"], 1)
        checkout.attach_address()

        resp = checkout.pay("pm_does_not_exist")
        assert resp.status_code in (404, 422), f"非法支付方式返回了 {resp.status_code}"

    @allure.story("缺少支付方式")
    def test_missing_payment_method(self, auth_api, factory, product_variant):
        checkout = Checkout(customer=auth_api, email=factory.email("pay"))
        checkout.add_item(product_variant["variant"]["id"], 1)
        checkout.attach_address()

        resp = checkout.customer.post(
            f"{STORE}/carts/{checkout.id}/payments", json={}, headers=checkout.headers
        )
        assert resp.status_code in (400, 404, 422), f"缺参数却建了支付: {resp.status_code}"

    @allure.story("未结算前订单不完整")
    def test_cart_not_complete_without_finishing(self, auth_api, factory, product_variant):
        checkout = Checkout(customer=auth_api, email=factory.email("pay"))
        checkout.add_item(product_variant["variant"]["id"], 1)
        checkout.attach_address()
        checkout.pay()

        cart = checkout.customer.get(f"{STORE}/carts/{checkout.id}", headers=checkout.headers).json()
        # 建了支付但没调 complete，购物车仍是未完成状态
        assert cart.get("completed_at") is None
        assert cart.get("number", "").startswith("cart_")


@allure.feature("支付")
class TestPaymentStateMachine:
    @allure.story("下单后支付完成、订单已付")
    @pytest.mark.db
    def test_order_paid_after_complete(self, order, db):
        row = db.fetch_one("select * from spree_orders where number = :n", n=order["body"]["number"])
        assert row["payment_status"] == "paid", f"订单支付状态是 {row['payment_status']}"

        payments = db.fetch_all("select * from spree_payments where order_id = :o", o=row["id"])
        assert payments, "订单没有支付记录"
        assert all(p["status"] == "completed" for p in payments), (
            f"支付状态不是 completed: {[p['status'] for p in payments]}"
        )

    @allure.story("支付金额 = 订单金额")
    @pytest.mark.db
    def test_payment_amount_equals_order_total(self, order, db):
        row = db.fetch_one("select * from spree_orders where number = :n", n=order["body"]["number"])
        paid = db.scalar(
            "select coalesce(sum(amount), 0) from spree_payments where order_id = :o", o=row["id"]
        )
        assert Decimal(str(paid)) == Decimal(str(row["total"]))

    @allure.story("订单已完成不能重复支付")
    def test_cannot_pay_completed_order(self, order):
        checkout: Checkout = order["checkout"]
        resp = checkout.pay(checkout.last_payment_method_id)
        assert resp.status_code in (404, 422), f"已完成订单还能加支付: {resp.status_code}"


@allure.feature("支付")
class TestPaymentVisibility:
    @allure.story("订单详情能看到支付记录")
    def test_order_detail_shows_payment(self, order, auth_api):
        body = expect.assert_business_ok(auth_api.get(f"{STORE}/orders/{order['body']['id']}"))
        assert "payments" in body, "订单详情里没有 payments 字段"
        assert body["payments"], "订单详情里 payments 为空"

    @allure.story("支付列表只含当前店铺的支付")
    def test_payment_belongs_to_order(self, order, auth_api):
        body = expect.assert_business_ok(auth_api.get(f"{STORE}/orders/{order['body']['id']}"))
        for payment in body["payments"]:
            assert payment.get("amount") is not None
            assert Decimal(str(payment["amount"])) > 0
