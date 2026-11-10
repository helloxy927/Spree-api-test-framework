"""用户资料（6 条，正常 5 / 异常 1）。

v3 的顾客接口是 `/customers/me*`，v2 的 `/account`、`/orders` 已经不存在（404）。
"""

from __future__ import annotations

import json

import allure
import pytest

from framework import assertions as expect

STORE = "/api/v3/store"
pytestmark = [pytest.mark.user]


@allure.feature("用户")
class TestProfile:
    @allure.story("查询个人资料")
    @pytest.mark.db
    def test_get_me_matches_database(self, auth_api, db, settings):
        resp = auth_api.get(f"{STORE}/customers/me")
        body = expect.assert_business_ok(resp)

        expect.assert_fields(body, email=settings.customer_email)
        row = db.fetch_one(
            "select id, email, first_name, last_name from spree_customers where email = :e",
            e=settings.customer_email,
        )
        assert row, "数据库里没有该顾客"
        expect.assert_fields(body, first_name=row["first_name"], last_name=row["last_name"])

    @allure.story("修改姓名字段")
    @pytest.mark.db
    def test_update_first_name_persists(self, auth_api, db, settings):
        original = db.scalar(
            "select first_name from spree_customers where email = :e", e=settings.customer_email
        )
        new_name = "QA-Updated"
        try:
            resp = auth_api.patch(f"{STORE}/customers/me", json={"first_name": new_name})
            body = expect.assert_business_ok(resp)
            expect.assert_fields(body, first_name=new_name)

            expect.assert_db_value(
                db,
                "select first_name from spree_customers where email = :e",
                new_name,
                e=settings.customer_email,
            )
        finally:
            auth_api.patch(f"{STORE}/customers/me", json={"first_name": original})

    @allure.story("资料不返回敏感字段")
    def test_profile_does_not_leak_secrets(self, auth_api):
        body = expect.assert_business_ok(auth_api.get(f"{STORE}/customers/me"))
        text = json.dumps(body).lower()
        for secret in ("password", "password_digest", "encrypted_password", "token"):
            assert secret not in text, f"接口返回了敏感字段 {secret}"

    @allure.story("未登录访问资料")
    def test_get_me_requires_token(self, api):
        resp = api.get(f"{STORE}/customers/me")
        expect.assert_business_error(resp, http_status=401)


@allure.feature("用户")
class TestCustomerOrders:
    @allure.story("我的订单列表")
    def test_list_my_orders(self, auth_api):
        body = expect.assert_business_ok(auth_api.get(f"{STORE}/customers/me/orders"))
        assert isinstance(body.get("data"), list)
        assert "meta" in body

    @allure.story("我的地址列表")
    def test_list_my_addresses(self, auth_api):
        body = expect.assert_business_ok(auth_api.get(f"{STORE}/customers/me/addresses"))
        assert isinstance(body.get("data"), list)
