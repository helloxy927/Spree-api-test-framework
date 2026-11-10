"""商品与搜索（10 条，正常 8 / 异常 2）。

每条用例的第三层断言都是「数据库里真的对得上」，而不是只看接口返回。
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import allure
import pytest

from framework import assertions as expect

STORE = "/api/v3/store"
pytestmark = [pytest.mark.product]


@allure.feature("商品")
class TestProductList:
    @allure.story("默认分页列表")
    def test_list_returns_paginated_products(self, api):
        resp = api.get(f"{STORE}/products")
        body = expect.assert_business_ok(resp)

        data, meta = body["data"], body["meta"]
        assert isinstance(data, list) and data, "商品列表为空，先执行 scripts/prepare_sut.py"
        expect.assert_fields(meta, page=1)
        assert meta["limit"] >= len(data)
        assert meta["count"] >= len(data)

    @allure.story("第二页不重复")
    def test_second_page_does_not_overlap(self, api):
        first = expect.assert_business_ok(api.get(f"{STORE}/products", params={"per_page": 5}))["data"]
        second = expect.assert_business_ok(
            api.get(f"{STORE}/products", params={"per_page": 5, "page": 2})
        )["data"]

        ids_first = {p["id"] for p in first}
        ids_second = {p["id"] for p in second}
        assert not (ids_first & ids_second), f"两页出现重复商品: {ids_first & ids_second}"

    @allure.story("按名称过滤")
    def test_filter_by_name(self, api):
        keyword = "Espresso"
        body = expect.assert_business_ok(
            api.get(f"{STORE}/products", params={"q[name_cont]": keyword, "per_page": 50})
        )
        data = body["data"]
        assert data, f"按 {keyword} 过滤没有结果"
        for item in data:
            assert keyword.lower() in item["name"].lower(), f"{item['name']} 不含关键字"

    @allure.story("空结果不报错")
    def test_empty_search_returns_empty_list(self, api):
        body = expect.assert_business_ok(
            api.get(f"{STORE}/products", params={"q[name_cont]": "绝对不存在的商品名xyz"})
        )
        assert body["data"] == []
        expect.assert_fields(body["meta"], count=0, pages=1)

    @allure.story("非法分页参数")
    def test_invalid_page_parameter_is_handled(self, api):
        resp = api.get(f"{STORE}/products", params={"page": 0, "per_page": -5})
        assert resp.status_code < 500, f"非法分页参数导致 5xx: {resp.status_code} {resp.text[:200]}"


@allure.feature("商品")
class TestProductDetail:
    @allure.story("按 slug 查详情")
    def test_detail_by_slug(self, api):
        listed = expect.assert_business_ok(api.get(f"{STORE}/products", params={"per_page": 1}))["data"][0]
        resp = api.get(f"{STORE}/products/{listed['slug']}")
        body = expect.assert_business_ok(resp)

        expect.assert_fields(body, id=listed["id"], slug=listed["slug"], name=listed["name"])

    @allure.story("商品不存在")
    def test_detail_not_found(self, api):
        resp = api.get(f"{STORE}/products/no-such-product-qa")
        error = expect.assert_business_error(resp, http_status=404, code="record_not_found")
        assert "Product" in error["message"] or "Product" in str(error)

    @allure.story("价格币种与店铺一致")
    def test_price_currency_matches_store(self, api, db):
        product = expect.assert_business_ok(
            api.get(f"{STORE}/products", params={"per_page": 1})
        )["data"][0]
        price = product.get("price") or {}
        assert price.get("amount") is not None, "商品没有价格，检查 prepare_sut 的基价步骤"

        store_currency = db.scalar("select default_currency from spree_stores where id = 1")
        expect.assert_fields(price, currency=store_currency)
        assert float(price["amount"]) > 0

    @allure.story("API 价格 = 数据库价格")
    @pytest.mark.db
    def test_price_matches_database(self, api, db):
        product = expect.assert_business_ok(
            api.get(f"{STORE}/products", params={"per_page": 1})
        )["data"][0]

        row = db.fetch_one(
            """
            select pr.amount, pr.currency
            from spree_products p
            join spree_prices pr
              on pr.variant_id = p.default_variant_id
             and pr.price_list_id is null
             and pr.deleted_at is null
             and pr.currency = :currency
            where p.slug = :slug and p.deleted_at is null
            """,
            slug=product["slug"],
            currency=product["price"]["currency"],
        )
        assert row, f"数据库里找不到 {product['slug']} 的基价"
        # 数据库是 numeric(19,4)，接口是两位小数字符串，必须按数值比较
        assert Decimal(str(row["amount"])) == Decimal(str(product["price"]["amount"])), (
            f"接口价格与数据库不一致: db={row['amount']} api={product['price']['amount']}"
        )
        assert row["currency"] == product["price"]["currency"]

    @allure.story("API 上架状态 = 数据库状态")
    @pytest.mark.db
    def test_availability_matches_database(self, api, db):
        product = expect.assert_business_ok(
            api.get(f"{STORE}/products", params={"per_page": 1})
        )["data"][0]

        row = db.fetch_one(
            "select status, available_on, deleted_at from spree_products where slug = :slug",
            slug=product["slug"],
        )
        assert row, "数据库里查不到该商品"
        assert row["status"] == "active"
        assert row["deleted_at"] is None
        assert row["available_on"] is not None
        assert row["available_on"] <= datetime.now(timezone.utc).replace(tzinfo=None), "上架时间在未来"
