"""
Inventory Service (Scoped)
実装ロードマップ Phase4: 在庫一覧の参照と、reorder_point(発注点)割れの異常検知を行う。
demo/prod デュアルモードは CustomerService/OrderService と同じ方針で分岐する
(demo_mode=true は DemoDataStore、false は本番DBリポジトリ未接続として拡張点を残す)。
"""
from datetime import datetime

from app.config import Settings
from app.services.demo_data import DemoDataStore


class InventoryService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store

    def list(self) -> list[dict]:
        if self.settings.demo_mode:
            return self.store.list_products()
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

    def get(self, pid: int) -> dict | None:
        if self.settings.demo_mode:
            return self.store.get_product(pid)
        raise NotImplementedError

    def create(self, data: dict) -> dict:
        if self.settings.demo_mode:
            return self.store.create_product(data)
        raise NotImplementedError

    def update(self, pid: int, data: dict) -> dict | None:
        if self.settings.demo_mode:
            return self.store.update_product(pid, data)
        raise NotImplementedError

    def anomalies(self) -> dict:
        """stock < reorder_point の商品を不足数の大きい順に返す。stock==0はcritical、それ以外はwarning。
        外部AIには依存しない(predictive_service.py同様、閾値判定だけで完結する軽量ロジック)。
        """
        products = self.list()
        found = []
        for p in products:
            shortage = p["reorder_point"] - p["stock"]
            if shortage > 0:
                found.append({
                    "product_id": p["id"],
                    "product_name": p["name"],
                    "stock": p["stock"],
                    "reorder_point": p["reorder_point"],
                    "shortage": shortage,
                    "severity": "critical" if p["stock"] == 0 else "warning",
                })
        found.sort(key=lambda a: a["shortage"], reverse=True)
        return {"generated_at": datetime.utcnow(), "anomalies": found}
