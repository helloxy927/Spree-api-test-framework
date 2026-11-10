"""统一 HTTP 客户端：鉴权头、超时、重试、耗时统计、报文留存都在这一层。

用例只写业务语义，不直接碰 requests。换被测系统时，理论上只需要改这个文件。
"""

from __future__ import annotations

import time
from typing import Any

import requests

from . import reporting
from .config import Settings

# 只对「基础设施类」错误重试：429 限流、502/503/504 网关抖动。
# 业务错误（4xx）绝不重试，否则会把真实缺陷掩盖掉。
RETRYABLE_STATUS = {429, 502, 503, 504}


class ApiClient:
    def __init__(
        self,
        settings: Settings,
        token: str | None = None,
        api_key: str | None = None,
    ) -> None:
        self.settings = settings
        self.token = token
        self.session = requests.Session()
        self.session.headers.update(
            {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "spree-api-test-framework/1.0",
            }
        )
        key = settings.api_key if api_key is None else api_key
        if key:
            self.session.headers["X-Spree-Api-Key"] = key
        if token:
            self.session.headers["Authorization"] = f"Bearer {token}"

    # ---------------- 构造 ----------------
    def clone(self, token: str | None = None, api_key: str | None = None) -> "ApiClient":
        """复制一个同配置客户端，用来切换身份（游客 / 普通用户 / 越权用户）。"""
        return ApiClient(self.settings, token=token, api_key=api_key)

    def _url(self, path: str) -> str:
        if path.startswith("http"):
            return path
        return f"{self.settings.base_url}/{path.lstrip('/')}"

    # ---------------- 核心 ----------------
    def request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: Any = None,
        headers: dict | None = None,
        timeout: int | None = None,
        retries: int | None = None,
    ) -> requests.Response:
        url = self._url(path)
        timeout = timeout or self.settings.timeout
        retries = self.settings.retries if retries is None else retries
        attempt = 0

        while True:
            attempt += 1
            started = time.perf_counter()
            try:
                resp = self.session.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json,
                    headers=headers,
                    timeout=timeout,
                )
            except requests.RequestException:
                if attempt > retries:
                    raise
                time.sleep(0.5 * attempt)
                continue

            elapsed_ms = int((time.perf_counter() - started) * 1000)
            resp.elapsed_ms = elapsed_ms  # type: ignore[attr-defined]

            if resp.status_code in RETRYABLE_STATUS and attempt <= retries:
                time.sleep(0.5 * attempt)
                continue

            if self.settings.attach_all:
                reporting.attach_exchange(
                    method=method,
                    url=url,
                    request_headers={**dict(self.session.headers), **(headers or {})},
                    request_body=json,
                    status_code=resp.status_code,
                    response_headers=dict(resp.headers),
                    response_body=resp.text,
                    elapsed_ms=elapsed_ms,
                )
            return resp

    # ---------------- 快捷方法 ----------------
    def get(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("POST", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("PATCH", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> requests.Response:
        return self.request("DELETE", path, **kwargs)

    def close(self) -> None:
        self.session.close()
