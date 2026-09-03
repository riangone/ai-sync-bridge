"""
クロス分析サービス (複数エンティティを跨いだ集計・分析 + チャート用データ生成)
================================================================
背景: nlsql_service(5.4.11差分実装)は「単一エンティティに対する自然文フィルタ」しか
扱えない。実務で頻度高く必要になる「与信リスク」「在庫逼迫」「滞留債権(焦げ付き)」は
いずれも複数エンティティを突き合わせないと算出できないため、別モジュールとして
用意した。

predictive_service と同じ設計方針を踏襲する:
  - 集計・判定ロジックそのものは外部AIを一切呼び出さない(閾値比較・合計・日数計算のみ)。
    AIプロバイダ未設定の環境でも本体機能(数値・チャート・一覧)は常に使えるようにする。
  - AIは insight_service 経由のオプトイン解釈コメントとしてのみ関与する(既存の
    予測分析/ワークフロー/管理と同一パターン)。
  - データ取得元は demo-legacy-system の読み取り専用API (/api/{entity}/list) のみ。
    レガシー側への変更・追加エンドポイント要求は一切ない(legacy_client経由、
    nlsql_serviceと共有)。

各レポートの戻り値は共通の形にしている(models/schemas.py の CrossAnalysisResponse):
  summary: 概況の数値まとめ
  chart:   狭いサイドバー幅でも読める「ランキング型横棒チャート」用データ
  rows:    テーブル表示用の明細行
  warnings: データ欠如等の注意事項
"""
from datetime import datetime

from app.config import Settings
from app.services import legacy_client

_TOP_N_CHART = 10  # サイドバー幅の都合上、チャートは上位N件のみ表示
_CONSUMPTION_WINDOW_DAYS = 180  # data.py の InventoryTransaction 生成期間(_rand_date(-180,0))に合わせる


def _to_float(v, default=0.0) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


def _parse_date(s: str | None):
    if not s:
        return None
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        return None


REPORTS = [
    {"id": "credit-risk", "label": "与信リスク分析(顧客×請求)", "unit": "円"},
    {"id": "stock-tension", "label": "在庫逼迫分析(商品×在庫トランザクション)", "unit": "日"},
    {"id": "bad-debt", "label": "滞留債権(延滞)分析(請求×顧客)", "unit": "円"},
]


class CrossAnalysisService:
    def __init__(self, settings: Settings):
        self.settings = settings

    async def list_reports(self) -> list[dict]:
        return REPORTS

    # -----------------------------------------------------------------
    # 1. 与信リスク分析: Customer × Invoice
    #    実与信エクスポージャー = 与信残高(CreditUsed) + 未回収請求(未払い+延滞)合計
    #    が 与信限度額(CreditLimit) に対してどの程度かを判定する。
    # -----------------------------------------------------------------
    async def credit_risk(self) -> dict:
        customers, _ = await legacy_client.fetch_rows(self.settings, "Customer")
        invoices, _ = await legacy_client.fetch_rows(self.settings, "Invoice")
        warnings = []
        if not customers:
            warnings.append("顧客データが空のため分析できません")

        unpaid_by_customer: dict[str, float] = {}
        overdue_by_customer: dict[str, float] = {}
        for inv in invoices:
            cid = inv.get("CustomerId")
            amount = _to_float(inv.get("TotalAmount"))
            if inv.get("Status") != "入金済":
                unpaid_by_customer[cid] = unpaid_by_customer.get(cid, 0.0) + amount
            if inv.get("Status") == "延滞":
                overdue_by_customer[cid] = overdue_by_customer.get(cid, 0.0) + amount

        rows = []
        for c in customers:
            cid = c.get("Id")
            limit = _to_float(c.get("CreditLimit"))
            used = _to_float(c.get("CreditUsed"))
            unpaid = unpaid_by_customer.get(cid, 0.0)
            overdue = overdue_by_customer.get(cid, 0.0)
            exposure = used + unpaid
            ratio = round(exposure / limit, 3) if limit > 0 else 0.0
            level = "超過" if ratio >= 1.0 else ("警戒" if ratio >= 0.8 else "正常")
            rows.append({
                "CustomerId": cid, "CustomerName": c.get("Name"),
                "CreditLimit": limit, "CreditUsed": used,
                "UnpaidInvoiceTotal": unpaid, "OverdueInvoiceTotal": overdue,
                "Exposure": round(exposure, 2), "UsageRatio": ratio, "RiskLevel": level,
            })
        rows.sort(key=lambda r: r["UsageRatio"], reverse=True)

        top = rows[:_TOP_N_CHART]
        chart = {
            "type": "ranked-bar-grouped", "unit": "円",
            "categories": [r["CustomerName"] for r in top],
            "series": [
                {"label": "与信限度額", "values": [r["CreditLimit"] for r in top]},
                {"label": "与信残高+未回収請求", "values": [r["Exposure"] for r in top]},
            ],
        }
        summary = {
            "customer_count": len(rows),
            "exceeded_count": sum(1 for r in rows if r["RiskLevel"] == "超過"),
            "warning_count": sum(1 for r in rows if r["RiskLevel"] == "警戒"),
            "total_exposure": round(sum(r["Exposure"] for r in rows), 2),
            "total_limit": round(sum(r["CreditLimit"] for r in rows), 2),
        }
        distribution = {
            "title": "リスク区分の内訳(全顧客)",
            "slices": [
                {"label": "正常", "count": sum(1 for r in rows if r["RiskLevel"] == "正常"), "status": "good"},
                {"label": "警戒(80%以上)", "count": summary["warning_count"], "status": "warning"},
                {"label": "超過", "count": summary["exceeded_count"], "status": "critical"},
            ],
        }
        return {
            "report": "credit-risk", "label": "与信リスク分析(顧客×請求)",
            "generated_at": datetime.utcnow(), "summary": summary, "chart": chart,
            "distribution": distribution, "rows": rows, "warnings": warnings,
        }

    # -----------------------------------------------------------------
    # 2. 在庫逼迫分析: Product × InventoryTransaction
    #    直近の出庫実績から日次消費ペースを推定し、現在庫での残り日数(在庫切れ予測)を
    #    算出する。安全在庫を下回っている、または残り日数が短い商品を「逼迫」とする。
    # -----------------------------------------------------------------
    async def stock_tension(self) -> dict:
        products, _ = await legacy_client.fetch_rows(self.settings, "Product")
        transactions, _ = await legacy_client.fetch_rows(self.settings, "InventoryTransaction")
        warnings = []
        if not products:
            warnings.append("商品データが空のため分析できません")

        outgoing_by_product: dict[str, float] = {}
        for tx in transactions:
            if tx.get("Type") != "出庫":
                continue
            pid = tx.get("ProductId")
            outgoing_by_product[pid] = outgoing_by_product.get(pid, 0.0) + abs(_to_float(tx.get("Quantity")))

        rows = []
        for p in products:
            pid = p.get("Id")
            stock = _to_float(p.get("Stock"))
            safety = _to_float(p.get("SafetyStock"))
            outgoing = outgoing_by_product.get(pid, 0.0)
            avg_daily_out = outgoing / _CONSUMPTION_WINDOW_DAYS
            days_of_stock = round(stock / avg_daily_out, 1) if avg_daily_out > 0 else None
            below_safety = stock < safety
            urgent = below_safety or (days_of_stock is not None and days_of_stock < 14)
            rows.append({
                "ProductId": pid, "ProductName": p.get("Name"), "Category": p.get("Category"),
                "Stock": stock, "SafetyStock": safety,
                "RecentOutgoingQty": outgoing, "AvgDailyConsumption": round(avg_daily_out, 2),
                "DaysOfStockRemaining": days_of_stock, "BelowSafetyStock": below_safety, "Urgent": urgent,
            })
        # 在庫切れまでの日数が短い順(データなし=無限大扱いで最後尾)にソート
        rows.sort(key=lambda r: r["DaysOfStockRemaining"] if r["DaysOfStockRemaining"] is not None else float("inf"))

        top = [r for r in rows if r["DaysOfStockRemaining"] is not None][:_TOP_N_CHART]
        chart = {
            "type": "ranked-bar", "unit": "日",
            "categories": [r["ProductName"] for r in top],
            "series": [{"label": "在庫切れまでの推定日数", "values": [r["DaysOfStockRemaining"] for r in top]}],
        }
        summary = {
            "product_count": len(rows),
            "urgent_count": sum(1 for r in rows if r["Urgent"]),
            "below_safety_count": sum(1 for r in rows if r["BelowSafetyStock"]),
        }
        # 安全在庫割れ(最重度) > 逼迫(urgentだが安全在庫は割れていない) > 正常、の3区分。
        # rows["Urgent"]は「below_safetyまたは残日数14日未満」の合成条件なので、
        # ここで排他的なバケットに分け直す(内訳の合計が商品数と一致するように)。
        below = summary["below_safety_count"]
        urgent_not_below = sum(1 for r in rows if r["Urgent"] and not r["BelowSafetyStock"])
        normal = len(rows) - below - urgent_not_below
        distribution = {
            "title": "在庫状態の内訳(全商品)",
            "slices": [
                {"label": "正常", "count": normal, "status": "good"},
                {"label": "逼迫(要注意)", "count": urgent_not_below, "status": "warning"},
                {"label": "安全在庫割れ", "count": below, "status": "critical"},
            ],
        }
        return {
            "report": "stock-tension", "label": "在庫逼迫分析(商品×在庫トランザクション)",
            "generated_at": datetime.utcnow(), "summary": summary, "chart": chart,
            "distribution": distribution, "rows": rows, "warnings": warnings,
        }

    # -----------------------------------------------------------------
    # 3. 滞留債権(焦げ付き)分析: Invoice(延滞) × Customer
    #    内訳集計の軸はinstanceで異なる: erpのCustomerはIndustry(業種)列を持つが、
    #    dealerのCustomerにはIndustry列自体が存在せず(CustomerType=法人/個人のみ)、
    #    Industryで集計すると全件「未設定」1本にまとまる無意味な内訳になる。
    #    web_search_service.py/panel-nlsql.jsのGENERATE_PRESETS_BY_INSTANCEと同じ
    #    「instanceで実在する属性に出し分ける」方針をここにも適用する。
    # -----------------------------------------------------------------
    async def bad_debt(self) -> dict:
        invoices, _ = await legacy_client.fetch_rows(self.settings, "Invoice")
        customers, _ = await legacy_client.fetch_rows(self.settings, "Customer")
        warnings = []
        customer_by_id = {c.get("Id"): c for c in customers}
        today = datetime.utcnow().date()
        is_dealer = self.settings.instance == "dealer"
        breakdown_field = "CustomerType" if is_dealer else "Industry"
        breakdown_label = "顧客区分(法人/個人)" if is_dealer else "業種"

        rows = []
        for inv in invoices:
            if inv.get("Status") != "延滞":
                continue
            due = _parse_date(inv.get("DueDate"))
            days_overdue = (today - due).days if due else None
            cust = customer_by_id.get(inv.get("CustomerId"), {})
            rows.append({
                "InvoiceId": inv.get("Id"), "CustomerId": inv.get("CustomerId"),
                "CustomerName": inv.get("CustomerName"), "TotalAmount": _to_float(inv.get("TotalAmount")),
                "InvoiceDate": inv.get("InvoiceDate"), "DueDate": inv.get("DueDate"),
                "DaysOverdue": days_overdue, "CustomerCreditLimit": _to_float(cust.get("CreditLimit")),
                "CustomerBreakdown": cust.get(breakdown_field),
            })
        if not rows:
            warnings.append("延滞状態の請求はありません")
        rows.sort(key=lambda r: r["TotalAmount"], reverse=True)

        by_customer: dict[str, dict] = {}
        for r in rows:
            entry = by_customer.setdefault(r["CustomerName"], {"CustomerName": r["CustomerName"], "Total": 0.0, "Count": 0})
            entry["Total"] += r["TotalAmount"]
            entry["Count"] += 1
        aggregated = sorted(by_customer.values(), key=lambda e: e["Total"], reverse=True)[:_TOP_N_CHART]

        by_breakdown: dict[str, dict] = {}
        for r in rows:
            key = r["CustomerBreakdown"] or "未設定"
            entry = by_breakdown.setdefault(key, {"Breakdown": key, "Total": 0.0, "Count": 0})
            entry["Total"] += r["TotalAmount"]
            entry["Count"] += 1
        breakdown_chart_data = sorted(by_breakdown.values(), key=lambda e: e["Total"], reverse=True)[:_TOP_N_CHART]

        chart = {
            "type": "ranked-bar", "unit": "円",
            "categories": [a["CustomerName"] for a in aggregated],
            "series": [{"label": "延滞金額(合計)", "values": [round(a["Total"], 2) for a in aggregated]}],
        }
        summary = {
            "overdue_invoice_count": len(rows),
            "overdue_total_amount": round(sum(r["TotalAmount"] for r in rows), 2),
            "affected_customer_count": len(by_customer),
            "by_breakdown_label": breakdown_label,
            "by_breakdown": [
                {"Breakdown": e["Breakdown"], "Total": round(e["Total"], 2), "Count": e["Count"]}
                for e in sorted(by_breakdown.values(), key=lambda e: e["Total"], reverse=True)
            ],
            "breakdown_chart": {
                "type": "ranked-bar", "unit": "円",
                "categories": [e["Breakdown"] for e in breakdown_chart_data],
                "series": [{"label": "延滞金額(合計)", "values": [round(e["Total"], 2) for e in breakdown_chart_data]}],
            },
        }
        # 延滞日数の経過度合いで3区分(日数不明分はカウントに含めない)。
        aging = [r["DaysOverdue"] for r in rows if r["DaysOverdue"] is not None]
        distribution = {
            "title": "延滞経過日数の内訳(延滞請求)",
            "slices": [
                {"label": "30日未満", "count": sum(1 for d in aging if d < 30), "status": "good"},
                {"label": "30〜60日", "count": sum(1 for d in aging if 30 <= d < 60), "status": "warning"},
                {"label": "60日以上", "count": sum(1 for d in aging if d >= 60), "status": "critical"},
            ],
        }
        return {
            "report": "bad-debt", "label": "滞留債権(延滞)分析(請求×顧客)",
            "generated_at": datetime.utcnow(), "summary": summary, "chart": chart,
            "distribution": distribution, "rows": rows, "warnings": warnings,
        }

    async def run(self, report: str) -> dict:
        if report == "credit-risk":
            return await self.credit_risk()
        if report == "stock-tension":
            return await self.stock_tension()
        if report == "bad-debt":
            return await self.bad_debt()
        raise ValueError(f"unknown report: {report}")
