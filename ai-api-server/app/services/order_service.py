"""Order Service (Scoped) - customer_service.py と同じ demo/prod dual mode パターン"""
# NOTE: このクラス内で `list` という名前のメソッドを定義すると、以降のメソッドの
# 戻り値注釈 `list[dict]` がクラス名前空間内の `list`(メソッド自身)に束縛されてしまい
# `'function' object is not subscriptable` で起動時エラーになる。
# from __future__ import annotations で注釈評価を遅延させ、この名前衝突を回避する。
from __future__ import annotations

from app.config import Settings
from app.services.demo_data import DemoDataStore


class OrderService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store  # demo_mode=false の場合はここを実DBリポジトリに差し替える

    def list(self) -> list[dict]:
        if self.settings.demo_mode:
            return self.store.list_orders()
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

    def get(self, oid: int) -> dict | None:
        if self.settings.demo_mode:
            return self.store.get_order(oid)
        raise NotImplementedError

    def create(self, data: dict) -> dict:
        if self.settings.demo_mode:
            return self.store.create_order(data)
        raise NotImplementedError

    def list_by_customer(self, cid: int) -> list[dict]:
        if self.settings.demo_mode:
            return self.store.list_orders_by_customer(cid)
        raise NotImplementedError
