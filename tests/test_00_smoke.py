"""冒烟用例：只验证「系统活着 + 鉴权生效」。

这两条是每次提交 / 每次定时任务的第一道闸，挂了就不该继续跑全量。
"""

from __future__ import annotations

import pytest

from framework import assertions as expect
from framework.client import ApiClient

STORE = "/api/v3/store"


@pytest.mark.smoke
@pytest.mark.product
def test_products_returns_list(api):
    resp = api.get(f"{STORE}/products")
    body = expect.assert_business_ok(resp)
    assert isinstance(body.get("data"), list), f"data 字段不是列表: {body}"


@pytest.mark.smoke
@pytest.mark.auth
@pytest.mark.negative
def test_missing_api_key_returns_401(settings):
    anonymous = ApiClient(settings, api_key="")
    try:
        resp = anonymous.get(f"{STORE}/products")
        expect.assert_business_error(resp, http_status=401, code="invalid_token")
    finally:
        anonymous.close()
