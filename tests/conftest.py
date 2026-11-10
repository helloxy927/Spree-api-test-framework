"""全局 fixture 与钩子。

约定：
- 会话级：settings / api / token / auth_api / db（只初始化一次，避免 60 个用例登录 60 次）
- 函数级：factory（每个用例自己造数据，结束后清理，用例之间零依赖）
"""

from __future__ import annotations

import pytest

from framework import reporting
from framework.auth import TokenManager
from framework.client import ApiClient
from framework.config import get_settings
from framework.data_factory import DataFactory
from framework.db import Database


def pytest_sessionstart(session: pytest.Session) -> None:
    """把运行环境写进 Allure 报告首页。"""
    settings = get_settings()
    try:
        allure_dir = session.config.getoption("--alluredir", default=None)
    except (ValueError, AttributeError):
        allure_dir = None
    if allure_dir:
        reporting.write_environment(allure_dir, settings)


@pytest.fixture(scope="session")
def settings():
    return get_settings()


@pytest.fixture(scope="session")
def api(settings):
    client = ApiClient(settings)
    yield client
    client.close()


@pytest.fixture(scope="session")
def token(settings, api) -> str:
    return TokenManager(api, settings.customer_email, settings.customer_password).token()


@pytest.fixture(scope="session")
def auth_api(settings, token) -> ApiClient:
    client = ApiClient(settings, token=token)
    yield client
    client.close()


@pytest.fixture(scope="session")
def db(settings) -> Database:
    if not settings.db_dsn:
        pytest.skip("未配置 DB_DSN，跳过需要数据库校验的用例")
    database = Database(settings.db_dsn)
    yield database
    database.close()


@pytest.fixture()
def factory(settings, request) -> DataFactory:
    data = DataFactory(settings.run_id)
    yield data

    if not data.created or not settings.db_dsn:
        return
    problems = data.cleanup(request.getfixturevalue("db"))
    if problems:
        print("\n[清理失败] 以下记录需要人工确认：")
        for problem in problems:
            print(f"  - {problem}")


STORE = "/api/v3/store"


@pytest.fixture(scope="session")
def product_variant(api) -> dict:
    """取一个有库存的商品及其首个 variant，供购物车/订单用例复用。"""
    product = api.get(f"{STORE}/products", params={"limit": 1}).json()["data"][0]
    detail = api.get(
        f"{STORE}/products/{product['slug']}", params={"expand": "variants"}
    ).json()
    return {"product": product, "variant": detail["variants"][0]}


@pytest.fixture()
def guest_cart(api, settings):
    """每个用例一个全新游客购物车，用例结束自动删掉，互不影响。"""
    from tests.helpers import GuestCart

    cart = GuestCart.create(api, settings)
    yield cart
    cart.destroy()


@pytest.fixture()
def order(auth_api, factory, product_variant) -> dict:
    """造一张已完成订单；需要中间状态的用例自己用 Checkout 走流程。"""
    from tests.helpers import Checkout

    checkout = Checkout(customer=auth_api, email=factory.email("buyer"))
    body = checkout.place_order(product_variant["variant"]["id"], 1)
    return {"body": body, "checkout": checkout}
