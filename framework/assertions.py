"""三层断言：HTTP 状态 -> 业务码/关键字段 -> 数据库状态。

为什么一定要三层：
- 只有第一层，接口返回 200 就过，接口内部吞异常你完全看不见；
- 加上第二层，能挡住「HTTP 200 但业务失败」；
- 加上第三层，才能挡住最贵的 bug：**接口说成功，数据没落库 / 落错了**。
"""

from __future__ import annotations

from typing import Any


def _json(resp: Any) -> dict:
    try:
        body = resp.json()
        return body if isinstance(body, dict) else {"data": body}
    except ValueError:
        return {}


def _context(resp: Any) -> str:
    method = getattr(getattr(resp, "request", None), "method", "?")
    return (
        f"{method} {resp.url} -> HTTP {resp.status_code}\n"
        f"响应: {(resp.text or '')[:800]}"
    )


# ---------------- 第一层：HTTP ----------------
def assert_status(resp: Any, expected: int = 200) -> None:
    assert resp.status_code == expected, f"HTTP 状态码不符，期望 {expected}\n{_context(resp)}"


# ---------------- 第二层：业务码 / 关键字段 ----------------
def assert_business_ok(resp: Any, expected_status: int = 200) -> dict:
    assert_status(resp, expected_status)
    body = _json(resp)
    assert not body.get("error"), f"业务返回错误\n{_context(resp)}"
    return body


def assert_business_error(resp: Any, *, http_status: int | None = None, code: str | None = None) -> dict:
    if http_status is not None:
        assert_status(resp, http_status)
    error = _json(resp).get("error") or {}
    assert error, f"期望返回 error 结构，实际没有\n{_context(resp)}"
    if code:
        assert error.get("code") == code, (
            f"业务错误码不符，期望 {code}，实际 {error.get('code')!r}\n{_context(resp)}"
        )
    return error


def assert_fields(payload: dict, **expected: Any) -> None:
    for key, value in expected.items():
        actual = payload.get(key) if isinstance(payload, dict) else None
        assert actual == value, f"字段 {key} 期望 {value!r}，实际 {actual!r}"


def assert_contains(payload: dict, key: str, expected: Any) -> None:
    actual = payload.get(key) if isinstance(payload, dict) else None
    assert expected in (actual or []), f"字段 {key} 应包含 {expected!r}，实际 {actual!r}"


# ---------------- 第三层：数据库 ----------------
def assert_db_value(db: Any, sql: str, expected: Any, **params: Any) -> Any:
    actual = db.scalar(sql, **params)
    assert actual == expected, (
        f"数据库校验失败：期望 {expected!r}，实际 {actual!r}\nSQL: {sql}\n参数: {params}"
    )
    return actual


def assert_db_exists(db: Any, sql: str, **params: Any) -> dict:
    row = db.fetch_one(sql, **params)
    assert row, f"数据库里查不到记录\nSQL: {sql}\n参数: {params}"
    return row


def assert_db_missing(db: Any, sql: str, **params: Any) -> None:
    row = db.fetch_one(sql, **params)
    assert row is None, f"数据库里不该存在的记录出现了: {row}"
