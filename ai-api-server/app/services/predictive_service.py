"""
Predictive Analytics Service (Scoped)
実装ロードマップ Phase3 ①: 受注データから売上トレンドを予測し、
顧客ごとの次回注文時期(再受注リスク)を推定する。

外部AIプロバイダを一切呼び出さない軽量な統計モデルのみで完結させている
(最小二乗法による線形回帰 / 平均発注間隔法)。理由は、AIプロバイダ未設定
(mock以外未接続)の環境でも予測機能自体は常に利用可能にしておきたいため。
需要が高まれば AiProvider に「トレンド解釈コメント生成」等を委譲する拡張点
として ai は将来引数に追加できる設計にしてある(現状は統計のみ)。
"""
from collections import defaultdict
from datetime import date, datetime, timedelta

from app.services.demo_data import DemoDataStore


def _parse_date(s: str) -> date:
    return datetime.strptime(s, "%Y-%m-%d").date()


def _month_key(d: date) -> str:
    return f"{d.year:04d}-{d.month:02d}"


def _add_months(d: date, n: int) -> date:
    month_index = d.month - 1 + n
    year = d.year + month_index // 12
    month = month_index % 12 + 1
    return date(year, month, 1)


class PredictiveService:
    def __init__(self, store: DemoDataStore):
        self.store = store

    def forecast_sales(self, months_ahead: int = 3) -> dict:
        """月次売上合計に最小二乗法で線形トレンドを当てはめ、未来 N ヶ月分を外挿する。"""
        orders = self.store.list_orders()
        monthly_totals: dict[str, float] = defaultdict(float)
        for o in orders:
            monthly_totals[_month_key(_parse_date(o["date"]))] += float(o["amount"])

        months_sorted = sorted(monthly_totals.keys())
        if not months_sorted:
            return {"method": "linear-regression", "history_months": 0, "forecast_months": months_ahead, "points": []}

        xs = list(range(len(months_sorted)))
        ys = [monthly_totals[m] for m in months_sorted]
        n = len(xs)
        mean_x = sum(xs) / n
        mean_y = sum(ys) / n
        denom = sum((x - mean_x) ** 2 for x in xs) or 1.0
        slope = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys)) / denom
        intercept = mean_y - slope * mean_x

        points = [
            {"month": m, "actual": round(monthly_totals[m], 2), "predicted": round(intercept + slope * i, 2)}
            for i, m in enumerate(months_sorted)
        ]

        last_month_start = _parse_date(months_sorted[-1] + "-01")
        for k in range(1, months_ahead + 1):
            future_x = n - 1 + k
            future_month = _month_key(_add_months(last_month_start, k))
            points.append({
                "month": future_month,
                "actual": None,
                "predicted": round(max(intercept + slope * future_x, 0.0), 2),
            })

        return {
            "method": "linear-regression",
            "history_months": len(months_sorted),
            "forecast_months": months_ahead,
            "points": points,
        }

    def predict_reorders(self) -> dict:
        """顧客ごとの平均発注間隔から次回発注予定日を推定し、overdue/due_soon/on_trackで分類する。"""
        orders = self.store.list_orders()
        by_customer: dict[int, list[date]] = defaultdict(list)
        for o in orders:
            by_customer[o["customer_id"]].append(_parse_date(o["date"]))

        customers = {c["id"]: c for c in self.store.list_customers()}
        today = datetime.utcnow().date()
        predictions = []
        for cid, dates in by_customer.items():
            if len(dates) < 2:
                continue  # 発注履歴が1件のみでは間隔を推定できない
            dates.sort()
            intervals = [(dates[i + 1] - dates[i]).days for i in range(len(dates) - 1)]
            avg_interval = sum(intervals) / len(intervals)
            last_date = dates[-1]
            expected_next = last_date + timedelta(days=avg_interval)
            days_until = (expected_next - today).days
            risk = "overdue" if days_until < 0 else ("due_soon" if days_until <= 14 else "on_track")
            c = customers.get(cid, {})
            predictions.append({
                "customer_id": cid,
                "customer_name": c.get("name", "不明"),
                "last_order_date": last_date.isoformat(),
                "avg_interval_days": round(avg_interval, 1),
                "expected_next_date": expected_next.isoformat(),
                "days_until_expected": days_until,
                "risk": risk,
            })

        predictions.sort(key=lambda p: p["days_until_expected"])
        return {"generated_at": datetime.utcnow(), "predictions": predictions}
