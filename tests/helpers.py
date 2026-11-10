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


@dataclass
class Checkout:
    """一次完整结算：建车 → 加购 → 挂地址 → 选支付方式 → 下单。

    结算链路本身有 5 个前置状态（email / ship_address / delivery / payment），
    收敛成一个对象后，订单和支付用例只需要「造一张单」这一句话。
    """

    customer: ApiClient
    email: str

    def __post_init__(self) -> None:
        self.cart = self.customer.post(f"{STORE}/carts").json()
        self.id: str = self.cart["id"]
        self.token: str = self.cart["token"]
        self.headers = {"X-Spree-Token": self.token}
        self.address_id: str | None = None
        self.last_payment_method_id: str | None = None

    # ---------------- 步骤 ----------------
    def add_item(self, variant_id: str, quantity: int = 1):
        return self.customer.post(
            f"{STORE}/carts/{self.id}/items",
            json={"variant_id": variant_id, "quantity": quantity},
            headers=self.headers,
        )

    def attach_address(self, **overrides) -> str:
        payload = {
            "first_name": "QA",
            "last_name": "Bot",
            "address1": "1 Test Road",
            "city": "Shanghai",
            "postal_code": "200000",
            "phone": "13800000000",
            "country_iso": "CN",
            "state_name": "Shanghai",
            **overrides,
        }
        resp = self.customer.post(f"{STORE}/customers/me/addresses", json=payload)
        assert resp.status_code in (200, 201), f"建地址失败: {resp.status_code} {resp.text[:300]}"
        self.address_id = resp.json()["id"]
        self.customer.patch(
            f"{STORE}/carts/{self.id}",
            json={
                "email": self.email,
                "ship_address_id": self.address_id,
                "bill_address_id": self.address_id,
            },
            headers=self.headers,
        )
        return self.address_id

    def payment_methods(self) -> list[dict]:
        cart = self.customer.get(f"{STORE}/carts/{self.id}", headers=self.headers).json()
        return cart.get("payment_methods") or []

    def pay(self, payment_method_id: str | None = None):
        if payment_method_id is None:
            payment_method_id = self.payment_methods()[0]["id"]
        self.last_payment_method_id = payment_method_id
        return self.customer.post(
            f"{STORE}/carts/{self.id}/payments",
            json={"payment_method_id": payment_method_id},
            headers=self.headers,
        )

    def complete(self):
        return self.customer.post(f"{STORE}/carts/{self.id}/complete", headers=self.headers)

    def place_order(self, variant_id: str, quantity: int = 1) -> dict:
        self.add_item(variant_id, quantity)
        self.attach_address()
        resp = self.pay()
        assert resp.status_code in (200, 201), f"支付失败: {resp.status_code} {resp.text[:300]}"
        done = self.complete()
        assert done.status_code == 200, f"下单失败: {done.status_code} {done.text[:300]}"
        return done.json()
