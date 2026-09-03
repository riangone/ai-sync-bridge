"""
Purchase Order Service (Scoped)
実装ロードマップ Phase4: 発注提案(ルールベース) + 入荷登録(goods-receipt) + 仕入先評価。

発注提案は predictive_service.py と同じ方針で、外部AIプロバイダを呼ばない軽量な
ルールベース(reorder_point割れ量から発注数量を算出)で完結させる。理由は同じく、
AIプロバイダ未接続(mock以外)の環境でも発注提案機能自体は常に利用可能にしておきたいため。
UI側のボタン文言・フィールド名からも「AI」の語を外し、本物のAI解釈と混同されないように
している。本物のAI解釈が欲しい場合は insight_service.interpret_purchase_proposal 経由の
GET /api/purchase-order/propose/insight (完全にオプトイン)を使う。
"""
from datetime import datetime

from app.config import Settings
from app.services.demo_data import DemoDataStore


class PurchaseOrderService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store

    def list(self) -> list[dict]:
        if self.settings.demo_mode:
            return self.store.list_purchase_orders()
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

    def get(self, poid: int) -> dict | None:
        if self.settings.demo_mode:
            return self.store.get_purchase_order(poid)
        raise NotImplementedError

    def create(self, data: dict) -> dict:
        if self.settings.demo_mode:
            payload = {**data, "ordered_at": datetime.utcnow().date().isoformat()}
            return self.store.create_purchase_order(payload)
        raise NotImplementedError

    def propose(self) -> dict:
        """在庫の reorder_point 割れ商品ごとに、発注点の2倍まで補充する数量を提案する。
        (安全在庫の考え方: 発注点そのものまで戻すだけでは次の消費で再度割れるため、
        余裕を持って reorder_point*2 - stock を提案数量とする)
        """
        if not self.settings.demo_mode:
            raise NotImplementedError
        proposals = []
        for p in self.store.list_products():
            if p["stock"] < p["reorder_point"]:
                suggested_qty = max(1, p["reorder_point"] * 2 - p["stock"])
                reason = (
                    f"在庫{p['stock']}が発注点{p['reorder_point']}を下回っています"
                    if p["stock"] > 0
                    else "在庫が枯渇しています(欠品中)"
                )
                proposals.append({
                    "product_id": p["id"],
                    "product_name": p["name"],
                    "current_stock": p["stock"],
                    "reorder_point": p["reorder_point"],
                    "suggested_qty": suggested_qty,
                    "supplier": p["supplier"],
                    "reason": reason,
                })
        proposals.sort(key=lambda pr: pr["current_stock"])
        return {"generated_at": datetime.utcnow(), "proposals": proposals}

    def receive_goods(self, po_id: int, received_qty: int) -> dict:
        """入荷登録: 発注に対する入荷数を積み上げ、在庫を増やす。qty分すべて揃ったらstatus=received。"""
        if not self.settings.demo_mode:
            raise NotImplementedError
        po = self.store.get_purchase_order(po_id)
        if not po:
            raise ValueError("purchase order not found")
        new_received = po.get("received_qty", 0) + received_qty
        status = "received" if new_received >= po["qty"] else "ordered"
        update = {"received_qty": new_received, "status": status}
        if status == "received":
            update["received_at"] = datetime.utcnow().date().isoformat()
        po = self.store.update_purchase_order(po_id, update)
        self.store.adjust_stock(po["product_id"], received_qty)
        return po

    def evaluate_suppliers(self) -> dict:
        """仕入先ごとに発注件数/総数量/納期遵守率を集計する。
        納期遵守率は「status==received かつ received_at <= expected_date」の割合
        (expected_date未設定のPOは分母から除外し、判定不能を遵守として誤カウントしない)。
        """
        if not self.settings.demo_mode:
            raise NotImplementedError
        pos = self.store.list_purchase_orders()
        by_supplier: dict[str, list[dict]] = {}
        for po in pos:
            by_supplier.setdefault(po["supplier"], []).append(po)

        evaluations = []
        for supplier, orders in by_supplier.items():
            total_qty = sum(o["qty"] for o in orders)
            judged = [o for o in orders if o["status"] == "received" and o.get("expected_date")]
            on_time = [
                o for o in judged
                if o.get("received_at") and o["received_at"] <= o["expected_date"]
            ]
            on_time_rate = round(len(on_time) / len(judged), 2) if judged else 1.0
            rating = "good" if on_time_rate >= 0.8 else ("normal" if on_time_rate >= 0.5 else "caution")
            evaluations.append({
                "supplier": supplier,
                "order_count": len(orders),
                "total_qty": total_qty,
                "on_time_rate": on_time_rate,
                "rating": rating,
            })
        evaluations.sort(key=lambda e: e["on_time_rate"])
        return {"generated_at": datetime.utcnow(), "evaluations": evaluations}
