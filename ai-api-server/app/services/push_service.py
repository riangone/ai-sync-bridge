"""
Push Notification / Alert Check Service (Scoped)
実装ロードマップ Phase4: README 5.3節 プッシュ通知系
(POST /api/push/check, /api/push/subscribe, /api/push/unsubscribe, GET /api/push/subscriptions)、
5.4.14「AlertCheckService」、7.2節 PushSubscriptions テーブル。

check() は独自の異常検知ロジックを新たに持たず、既に実装済みの Phase4 サービス群
(InventoryService.anomalies() / ArApService.aging()) の出力を「アラート」という
共通フォーマットに集約するだけの薄い合成レイヤーにする。判定ロジックを二重実装すると
閾値の変更漏れ等でズレる恐れがあるため、あえて計算はしない。
severity は README 5.1「severity別色分け: high=赤, medium=黄, info=青」に合わせて
critical在庫異常/売掛の高リスクを high、警告レベルの在庫異常/買掛の高リスクを medium とする。

購読管理(subscribe/unsubscribe/list)は他の Phase4 サービス(Inventory/PurchaseOrder等)と
同じ demo/prod 分岐 + NotImplementedError 方針を踏襲する。summary はここでも
外部AIプロバイダを呼ばず、ルールベースの文言生成のみで完結させる
(ar_ap_service.py / profit_report_service.py と同方針)。
本物のAI解釈が欲しい場合は insight_service.interpret_alerts 経由の
GET /api/push/check/insight (完全にオプトイン)を使う。
"""
from datetime import datetime

from app.config import Settings
from app.services.ar_ap_service import ArApService
from app.services.demo_data import DemoDataStore
from app.services.inventory_service import InventoryService


class PushService:
    def __init__(
        self,
        settings: Settings,
        store: DemoDataStore,
        inventory_service: InventoryService,
        ar_ap_service: ArApService,
    ):
        self.settings = settings
        self.store = store
        self.inventory_service = inventory_service
        self.ar_ap_service = ar_ap_service

    # ---- Alert check (README: POST /api/push/check) ----
    def check(self) -> dict:
        alerts: list[dict] = []

        for a in self.inventory_service.anomalies()["anomalies"]:
            alerts.append({
                "source": "inventory",
                "severity": "high" if a["severity"] == "critical" else "medium",
                "title": f"{a['product_name']} が発注点割れ",
                "message": f"在庫{a['stock']}個(発注点{a['reorder_point']}個、不足{a['shortage']}個)",
                "ref_type": "product",
                "ref_id": a["product_id"],
            })

        # 本番モードで ArApService が NotImplementedError を投げても、在庫アラートまでは
        # 返せるようにする(1つのデータソースの未実装が全体を巻き込んで落ちないようにする)。
        try:
            aging = self.ar_ap_service.aging()
        except NotImplementedError:
            aging = None
        if aging:
            for r in aging["aging_report"]:
                if r["risk"] != "high":
                    continue
                is_receivable = r["entity_type"] == "receivable"
                alerts.append({
                    "source": "ar_ap",
                    "severity": "high" if is_receivable else "medium",
                    "title": f"{r['entity_name']} の{'売掛金' if is_receivable else '買掛金'}が長期滞留",
                    "message": f"90日超滞留 {r['bucket_90_plus']:,.0f}円(合計{r['total']:,.0f}円)",
                    "ref_type": r["entity_type"],
                    "ref_id": None,
                })

        alerts.sort(key=lambda a: {"high": 0, "medium": 1, "info": 2}.get(a["severity"], 3))
        high_count = sum(1 for a in alerts if a["severity"] == "high")
        medium_count = sum(1 for a in alerts if a["severity"] == "medium")

        return {
            "generated_at": datetime.utcnow(),
            "alerts": alerts,
            "total_alerts": len(alerts),
            "high_count": high_count,
            "medium_count": medium_count,
            "summary": self._build_summary(alerts, high_count, medium_count),
        }

    @staticmethod
    def _build_summary(alerts: list[dict], high_count: int, medium_count: int) -> str:
        if not alerts:
            return "現在、対応が必要なアラートはありません。"
        lines = [f"未対応アラートが{len(alerts)}件あります(緊急{high_count}件・注意{medium_count}件)。"]
        top = alerts[0]
        lines.append(f"最優先: {top['title']}({top['message']})。")
        return " ".join(lines)

    # ---- Subscription management (README: subscribe/unsubscribe/subscriptions) ----
    def subscribe(self, endpoint: str, p256dh: str | None, auth: str | None, device_name: str | None) -> dict:
        if self.settings.demo_mode:
            return self.store.upsert_push_subscription({
                "endpoint": endpoint, "p256dh": p256dh, "auth": auth, "device_name": device_name,
            })
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

    def unsubscribe(self, endpoint: str) -> bool:
        if self.settings.demo_mode:
            return self.store.delete_push_subscription(endpoint)
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

    def list_subscriptions(self) -> list[dict]:
        if self.settings.demo_mode:
            return self.store.list_push_subscriptions()
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")
