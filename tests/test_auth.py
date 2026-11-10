"""登录与鉴权（9 条，正常 6 / 异常 3）。

注意：Spree 对 `POST /auth/login` 限流 5 次/分钟/IP、`POST /customers` 3 次/分钟/IP。
所以本模块里「真正发登录请求」的用例只有 3 条，其余用 GET 验证鉴权，
避免测试自己把自己打成 429。这也是框架里 TokenManager 必须做会话级缓存的原因。
"""

from __future__ import annotations

import time

import allure
import pytest

from framework import assertions as expect
from framework.auth import jwt_exp
from framework.client import ApiClient

STORE = "/api/v3/store"
pytestmark = [pytest.mark.auth]


@allure.feature("登录鉴权")
class TestLogin:
    @allure.story("正常登录")
    def test_login_success_returns_jwt(self, api, settings):
        resp = api.post(
            f"{STORE}/auth/login",
            json={"email": settings.customer_email, "password": settings.customer_password},
        )
        body = expect.assert_business_ok(resp)

        assert body.get("token"), "登录响应缺少 token"
        assert body.get("refresh_token"), "登录响应缺少 refresh_token"
        expect.assert_fields(body.get("user", {}), email=settings.customer_email)
        assert jwt_exp(body["token"]) > time.time(), "JWT 已过期"

    @allure.story("密码错误")
    def test_login_wrong_password(self, api, settings):
        resp = api.post(
            f"{STORE}/auth/login",
            json={"email": settings.customer_email, "password": "definitely-wrong-pass"},
        )
        error = expect.assert_business_error(resp, http_status=401, code="authentication_failed")
        assert "Invalid email or password" in error["message"]

    @allure.story("邮箱不存在")
    def test_login_unknown_email(self, api):
        resp = api.post(
            f"{STORE}/auth/login",
            json={"email": "nobody_qa@example.test", "password": "Whatever123!"},
        )
        error = expect.assert_business_error(resp, http_status=401, code="authentication_failed")
        # 不能泄露账号是否存在：与密码错误返回同一句提示
        assert "Invalid email or password" in error["message"]


@allure.feature("登录鉴权")
class TestApiKey:
    @allure.story("缺少 API Key")
    def test_missing_api_key_returns_401(self, settings):
        anonymous = ApiClient(settings, api_key="")
        try:
            resp = anonymous.get(f"{STORE}/products")
            expect.assert_business_error(resp, http_status=401, code="invalid_token")
        finally:
            anonymous.close()

    @allure.story("错误的 API Key")
    def test_invalid_api_key_returns_401(self, settings):
        broken = ApiClient(settings, api_key="pk_not_a_real_key_000000")
        try:
            resp = broken.get(f"{STORE}/products")
            expect.assert_business_error(resp, http_status=401, code="invalid_token")
        finally:
            broken.close()

    @allure.story("伪造 JWT")
    def test_forged_jwt_is_rejected(self, settings):
        forged = ApiClient(settings, token="header.payload.signature")
        try:
            resp = forged.get(f"{STORE}/customers/me")
            expect.assert_business_error(resp, http_status=401)
        finally:
            forged.close()


@allure.feature("注册")
class TestRegister:
    @allure.story("正常注册")
    @pytest.mark.db
    def test_register_new_customer(self, api, db, factory):
        email = factory.email("register")
        resp = api.post(
            f"{STORE}/customers",
            json={
                "email": email,
                "password": "Passw0rd!",
                "password_confirmation": "Passw0rd!",
                "first_name": "QA",
                "last_name": "Bot",
            },
        )
        expect.assert_status(resp, 201)
        body = resp.json()
        expect.assert_fields(body.get("user", body), email=email)

        expect.assert_db_value(
            db, "select count(*) from spree_customers where email = :e", 1, e=email
        )
        factory.record("spree_customers", "email", email)

    @allure.story("邮箱重复")
    @pytest.mark.db
    def test_register_duplicate_email(self, api, db, settings):
        resp = api.post(
            f"{STORE}/customers",
            json={
                "email": settings.customer_email,
                "password": "Passw0rd!",
                "password_confirmation": "Passw0rd!",
                "first_name": "QA",
                "last_name": "Bot",
            },
        )
        error = expect.assert_business_error(resp, http_status=422, code="validation_error")
        assert "email" in (error.get("details") or {})

        expect.assert_db_value(
            db,
            "select count(*) from spree_customers where email = :e",
            1,
            e=settings.customer_email,
        )

    @allure.story("两次密码不一致")
    def test_register_password_mismatch(self, api, factory):
        resp = api.post(
            f"{STORE}/customers",
            json={
                "email": factory.email("mismatch"),
                "password": "Passw0rd!",
                "password_confirmation": "Other123!",
                "first_name": "QA",
                "last_name": "Bot",
            },
        )
        error = expect.assert_business_error(resp, http_status=422, code="validation_error")
        assert "password_confirmation" in (error.get("details") or {})
