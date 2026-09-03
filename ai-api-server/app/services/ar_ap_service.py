"""
AR/AP Aging Service (Scoped)
実装ロードマップ Phase4: 売掛金(AR)/買掛金(AP)のエイジング分析(README 6.5.12 ArAp画面、
5.3節 POST /api/ar-ap/aging、5.4.14「ArApService: AR/APエイジング分析(30/60/90日以上区分)」)。

支払済(paid=true)の請求/未払は残高がゼロなので集計対象から除外する。バケット境界は
本日日付(datetime.utcnow())と due_date の差分日数で判定するため、デモシード(demo_data.py)
の日付が過去になるほど自然と滞留区分が進む(predictive_service.py の再受注リスク判定と同じ考え方)。

外部AIプロバイダは呼ばない。summary はエイジング集計結果からのルールベースの
コメント生成のみで完結させる(purchase_order_service.py / profit_report_service.py と同方針)。
本物のAI解釈が欲しい場合は insight_service.interpret_aging 経由の
GET /api/ar-ap/aging/insight (完全にオプトイン)を使う。
"""
from collections import defaultdict
from datetime import datetime

from app.config import Settings
from app.services.demo_data import DemoDataStore


def _parse_date(s: str):
    return datetime.strptime(s, "%Y-%m-%d").date()


def _bucket(days_overdue: int) -> str:
    if days_overdue <= 0:
        return "current"
    if days_overdue <= 30:
        return "1-30"
    if days_overdue <= 60:
        return "31-60"
    if days_overdue <= 90:
        return "61-90"
    return "90+"


class ArApService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store

    def aging(self) -> dict:
        if not self.settings.demo_mode:
            raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

        today = datetime.utcnow().date()
        customers = {c["id"]: c for c in self.store.list_customers()}

        ar_rows = self._aggregate(
            records=[i for i in self.store.list_invoices() if not i["paid"]],
            key_fn=lambda i: i["customer_id"],
            name_fn=lambda k: customers.get(k, {}).get("name", "不明"),
            entry_type="receivable",
            today=today,
        )
        ap_rows = self._aggregate(
            records=[p for p in self.store.list_payables() if not p["paid"]],
            key_fn=lambda p: p["supplier"],
            name_fn=lambda k: k,
            entry_type="payable",
            today=today,
        )

        total_receivable = sum(r["total"] for r in ar_rows)
        total_payable = sum(r["total"] for r in ap_rows)

        aging_report = ar_rows + ap_rows
        aging_report.sort(key=lambda r: (-r["bucket_90_plus"], -r["total"]))

        return {
            "generated_at": datetime.utcnow(),
            "aging_report": aging_report,
            "total_receivable": round(total_receivable, 2),
            "total_payable": round(total_payable, 2),
            "summary": self._build_summary(ar_rows, ap_rows, total_receivable, total_payable),
        }

    @staticmethod
    def _aggregate(records: list[dict], key_fn, name_fn, entry_type: str, today) -> list[dict]:
        grouped: dict = defaultdict(lambda: {
            "current": 0.0, "bucket_1_30": 0.0, "bucket_31_60": 0.0,
            "bucket_61_90": 0.0, "bucket_90_plus": 0.0,
        })
        for r in records:
            key = key_fn(r)
            days_overdue = (today - _parse_date(r["due_date"])).days
            bucket = _bucket(days_overdue)
            field = {
                "current": "current", "1-30": "bucket_1_30", "31-60": "bucket_31_60",
                "61-90": "bucket_61_90", "90+": "bucket_90_plus",
            }[bucket]
            grouped[key][field] += float(r["amount"])

        rows = []
        for key, buckets in grouped.items():
            total = sum(buckets.values())
            overdue_90_ratio = buckets["bucket_90_plus"] / total if total else 0.0
            risk = "high" if overdue_90_ratio >= 0.3 else ("medium" if buckets["bucket_61_90"] + buckets["bucket_90_plus"] > 0 else "low")
            rows.append({
                "entity_type": entry_type,
                "entity_name": name_fn(key),
                **{k: round(v, 2) for k, v in buckets.items()},
                "total": round(total, 2),
                "risk": risk,
            })
        return rows

    @staticmethod
    def _build_summary(ar_rows: list[dict], ap_rows: list[dict], total_receivable: float, total_payable: float) -> str:
        lines = [f"売掛金残高は{total_receivable:,.0f}円、買掛金残高は{total_payable:,.0f}円です。"]

        high_risk_ar = [r for r in ar_rows if r["risk"] == "high"]
        if high_risk_ar:
            names = "、".join(r["entity_name"] for r in high_risk_ar)
            lines.append(f"回収リスクが高い(90日超滞留が全体の30%以上)取引先: {names}。督促を優先してください。")

        high_risk_ap = [r for r in ap_rows if r["risk"] == "high"]
        if high_risk_ap:
            names = "、".join(r["entity_name"] for r in high_risk_ap)
            lines.append(f"支払遅延が90日を超えている仕入先: {names}。取引条件への影響に注意してください。")

        if not high_risk_ar and not high_risk_ap:
            lines.append("90日超の重大な滞留はありません。")

        return " ".join(lines)
