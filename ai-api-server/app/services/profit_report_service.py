"""
Profit Report Service (Scoped)
実装ロードマップ Phase4: 商品別売上/原価/粗利/粗利率レポート(README 6.5.12 Profit画面、
5.3節 POST /api/profit-report/report に対応)。

受注(orders)は商品マスタ(products)への外部キーを持たない(item は自由入力の商品名文字列)
ため、item と products.name の一致で原価(unit_cost)を突き合わせる。一致しない商品名は
原価不明(cost_known=false, cost=0)として扱い、粗利計算自体は落とさずに継続する
(purchase_order_service.py と同じく、欠損データで例外を投げず安全側にフォールバックする方針)。

外部AIプロバイダは呼ばない。predictive_service.py / purchase_order_service.py と同じ方針で、
summary は集計結果からのルールベースのコメント生成のみで完結させる。
本物のAI解釈が欲しい場合は insight_service.interpret_profit_report 経由の
GET /api/profit-report/report/insight (完全にオプトイン)を使う。
"""
from collections import defaultdict
from datetime import datetime

from app.config import Settings
from app.services.demo_data import DemoDataStore


class ProfitReportService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store

    def report(self, period: str | None = None) -> dict:
        """period は "YYYY-MM" 形式のプレフィックス絞り込み(未指定なら全期間)。"""
        if not self.settings.demo_mode:
            raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

        orders = self.store.list_orders()
        if period:
            orders = [o for o in orders if o["date"].startswith(period)]

        unit_cost_by_name = {p["name"]: p["unit_cost"] for p in self.store.list_products()}

        grouped: dict[str, dict] = defaultdict(lambda: {"revenue": 0.0, "qty": 0, "cost": 0.0, "cost_known": True})
        for o in orders:
            g = grouped[o["item"]]
            g["revenue"] += float(o["amount"])
            g["qty"] += int(o["qty"])
            unit_cost = unit_cost_by_name.get(o["item"])
            if unit_cost is None:
                g["cost_known"] = False  # 商品マスタに存在しない商品名(原価不明)
            else:
                g["cost"] += unit_cost * int(o["qty"])

        product_details = []
        total_profit = 0.0
        for name, g in grouped.items():
            profit = g["revenue"] - g["cost"]
            margin_rate = round(profit / g["revenue"], 4) if g["revenue"] else 0.0
            total_profit += profit
            product_details.append({
                "product_name": name,
                "qty": g["qty"],
                "revenue": round(g["revenue"], 2),
                "cost": round(g["cost"], 2),
                "profit": round(profit, 2),
                "margin_rate": margin_rate,
                "cost_known": g["cost_known"],
            })
        product_details.sort(key=lambda d: d["profit"], reverse=True)

        profit_data = [
            {"product_name": d["product_name"], "revenue": d["revenue"], "profit": d["profit"]}
            for d in product_details
        ]

        return {
            "generated_at": datetime.utcnow(),
            "period": period,
            "profit_data": profit_data,
            "product_details": product_details,
            "total_profit": round(total_profit, 2),
            "summary": self._build_summary(product_details, total_profit),
        }

    @staticmethod
    def _build_summary(product_details: list[dict], total_profit: float) -> str:
        if not product_details:
            return "対象期間の受注データがないため、利益分析を算出できませんでした。"

        lines = [f"総粗利は{total_profit:,.0f}円です。"]
        best = product_details[0]
        lines.append(f"最も粗利貢献度が高いのは「{best['product_name']}」(粗利{best['profit']:,.0f}円、粗利率{best['margin_rate']*100:.1f}%)。")

        low_margin = [d for d in product_details if d["cost_known"] and d["margin_rate"] < 0.2]
        if low_margin:
            names = "、".join(d["product_name"] for d in low_margin[:3])
            lines.append(f"粗利率20%未満の商品: {names}。値付けまたは仕入原価の見直しを検討してください。")

        unknown = [d["product_name"] for d in product_details if not d["cost_known"]]
        if unknown:
            names = "、".join(unknown[:3])
            lines.append(f"商品マスタに原価未登録のため粗利を正確に算出できない商品: {names}。")

        return " ".join(lines)
