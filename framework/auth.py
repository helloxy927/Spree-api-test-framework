"""Token 管理：登录一次、全 session 复用、临近过期自动刷新。

为什么不在每个用例里登录：
- 登录接口通常有频率限制，60+ 用例逐个登录会把自己打成 429；
- 每个用例多一次 RTT，整体执行时间翻倍；
- 刷新逻辑集中在一处，token 过期就不会变成「随机失败」。
"""

from __future__ import annotations

import base64
import json
import time

from .client import ApiClient

STORE = "/api/v3/store"


def jwt_exp(token: str) -> float:
    """从 JWT 的 payload 里读 exp；解不出来就保守按 1 小时算。"""
    try:
        segment = token.split(".")[1]
        segment += "=" * (-len(segment) % 4)
        payload = json.loads(base64.urlsafe_b64decode(segment))
        return float(payload["exp"])
    except Exception:
        return time.time() + 3600


class TokenManager:
    def __init__(self, client: ApiClient, email: str, password: str, margin: int = 300) -> None:
        self.client = client
        self.email = email
        self.password = password
        self.margin = margin
        self._token: str | None = None
        self._expires_at: float = 0.0

    def token(self) -> str:
        if self._token and time.time() < self._expires_at - self.margin:
            return self._token
        if self._token:
            return self.refresh()
        return self.login()

    def login(self) -> str:
        resp = self.client.post(
            f"{STORE}/auth/login",
            json={"email": self.email, "password": self.password},
        )
        token = self._extract(resp)
        self._remember(token)
        return token

    def refresh(self) -> str:
        resp = self.client.post(
            f"{STORE}/auth/refresh",
            headers={"Authorization": f"Bearer {self._token}"},
        )
        token = self._extract(resp)
        self._remember(token)
        return token

    @staticmethod
    def _extract(resp) -> str:
        if resp.status_code != 200:
            raise RuntimeError(f"登录失败: HTTP {resp.status_code} {resp.text[:500]}")
        body = resp.json()
        token = body.get("token") or (body.get("data") or {}).get("token")
        if not token:
            raise RuntimeError(f"登录响应里没有 token 字段: {body}")
        return token

    def _remember(self, token: str) -> None:
        self._token = token
        self._expires_at = jwt_exp(token)
