"""用例层的小工具：把「游客购物车」这类重复操作收敛到一处。

用例里只写业务动作（加购、改数量），不关心 token 放在哪个 header。
"""

from __future__ import annotations

from dataclasses import dataclass, field

import requests

from framework.client import ApiClient

STORE = "/api/v3/store"


@dataclass
class GuestCart:
    client: ApiClient
    id: str
    token: str
    raw: dict = field(default_factory=dict)

    @classmethod
    def create(cls, api: ApiClient, settings) -> "GuestCart":
        resp = api.post(f"{STORE}/carts")
        assert resp.status_code in (200, 201), f"创建购物车失败: {resp.status_code} {resp.text[:300]}"
        body = resp.json()
        client = ApiClient(settings)
        client.session.headers["X-Spree-Token"] = body["token"]
        return cls(client=client, id=body["id"], token=body["token"], raw=body)

    # ---------------- 业务动作 ----------------
    def add(self, variant_id: str, quantity: int = 1) -> requests.Response:
        return self.client.post(
            f"{STORE}/carts/{self.id}/items",
            json={"variant_id": variant_id, "quantity": quantity},
        )

    def update(self, item_id: str, quantity: int) -> requests.Response:
        return self.client.patch(
            f"{STORE}/carts/{self.id}/items/{item_id}",
            json={"quantity": quantity},
        )

    def remove(self, item_id: str) -> requests.Response:
        return self.client.delete(f"{STORE}/carts/{self.id}/items/{item_id}")

    def get(self) -> requests.Response:
        return self.client.get(f"{STORE}/carts/{self.id}")

    def items(self) -> list[dict]:
        return self.get().json().get("items", [])

    def total(self) -> str:
        return self.get().json().get("total", "0.00")

    def destroy(self) -> None:
        try:
            self.client.delete(f"{STORE}/carts/{self.id}")
        except Exception:  # noqa: BLE001 - 清理失败不影响用例结论
            pass
        finally:
            self.client.close()
