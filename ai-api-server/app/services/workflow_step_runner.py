"""
WorkflowStepRunner (Scoped)
README 5.4.10「アクションタイプ」9種(ocr/search/report/auto_input/push/recommend/chat/
wait/condition)の実行本体。

WorkflowEngine(Singleton)自身にOCR/検索/レポート等の実処理を持たせると、
既存の Scoped サービス群(OcrService/SearchService/…)と処理が二重化し、
仕様変更のたびに2箇所を直す羽目になる。そのため実行部分だけをこの Scoped
クラスに切り出し、WorkflowEngine.execute() からは
`await runner.run(action_type, config, context)` の1メソッドだけを呼ぶ形にした
(フロー制御とアクション実行の責務分離)。

各 run_xxx は (output, ok) のタプルを返す。output はそのまま
context["step_{order}_output"] に格納されるので、後続ステップの
{{step_N_output}} 参照や condition アクションの判定対象になる。
"""
import asyncio
import base64
from typing import Any

from app.config import Settings
from app.services.ai_client import AiProvider
from app.services.cross_analysis_service import CrossAnalysisService
from app.services.demo_data import DemoDataStore
from app.services.inventory_service import InventoryService
from app.services.notification_service import NotificationCenter
from app.services.ocr_service import OcrService
from app.services.predictive_service import PredictiveService
from app.services.recommend_service import RecommendService
from app.services.search_service import SearchService
from app.services.workflow_service import _CONDITION_OPERATORS

_WAIT_SECONDS_CAP = 5.0  # デモ/テスト実行がステップの待機で長時間ブロックされないようにする上限

# README 5.1「severity別色分け」に合わせたレベル正規化(push_service.pyと同じ対応表)
_SEVERITY_TO_LEVEL = {"critical": "critical", "high": "critical", "warning": "warning", "medium": "warning", "info": "info"}


def _truthy(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, (str, list, dict, tuple, set)):
        return len(value) > 0
    return bool(value)


class WorkflowStepRunner:
    def __init__(
        self,
        settings: Settings,
        store: DemoDataStore,
        ai: AiProvider,
        ocr_service: OcrService,
        search_service: SearchService,
        recommend_service: RecommendService,
        inventory_service: InventoryService,
        predictive_service: PredictiveService,
        cross_analysis_service: CrossAnalysisService,
        notification_center: NotificationCenter,
    ):
        self.settings = settings
        self.store = store
        self.ai = ai
        self.ocr_service = ocr_service
        self.search_service = search_service
        self.recommend_service = recommend_service
        self.inventory_service = inventory_service
        self.predictive_service = predictive_service
        self.cross_analysis_service = cross_analysis_service
        self.notification_center = notification_center

    async def run(self, action_type: str, config: dict, context: dict) -> tuple[Any, bool]:
        handler = getattr(self, f"_run_{action_type}", None)
        if handler is None:
            raise ValueError(f"未対応のactionType: {action_type}")
        return await handler(config, context)

    # ---- ocr: 設定(imageBase64, screenType) ----
    async def _run_ocr(self, config: dict, context: dict) -> tuple[dict, bool]:
        raw = config.get("imageBase64") or ""
        try:
            content = base64.b64decode(raw) if raw else b""
        except Exception:
            content = raw.encode("utf-8")
        filename = f"{config.get('screenType', 'unknown')}.png"
        result = await self.ocr_service.extract(filename, content, mime="image/png")
        return result, True

    # ---- search: 設定(keyword, table) ----
    async def _run_search(self, config: dict, context: dict) -> tuple[dict, bool]:
        keyword = config.get("keyword", "")
        # 現行の SearchService は顧客テーブルのベクトル検索のみ対応(README 5.4.13の
        # 汎用ANNインデックスは顧客のみをインデックス化している)。table指定は将来の
        # 複数テーブル対応に備えて結果に残すだけに留める。
        result = await self.search_service.search(keyword)
        result = {**result, "requested_table": config.get("table")}
        return result, True

    # ---- report: 設定(reportType=[stock/credit_risk/demand/customer/order], targetId?) ----
    async def _run_report(self, config: dict, context: dict) -> tuple[Any, bool]:
        report_type = config.get("reportType")
        if report_type == "stock":
            return self.inventory_service.anomalies(), True
        if report_type == "credit_risk":
            return await self.cross_analysis_service.credit_risk(), True
        if report_type == "demand":
            return self.predictive_service.forecast_sales(), True
        if report_type == "customer":
            customers = self.store.list_customers()
            active = sum(1 for c in customers if c.get("status") == "取引中")
            return {"count": len(customers), "active_count": active, "sample": customers[:5]}, True
        if report_type == "order":
            orders = self.store.list_orders()
            total = sum(o.get("amount", 0) for o in orders)
            return {"count": len(orders), "total_amount": total, "sample": orders[:5]}, True
        raise ValueError(f"未対応のreportType: {report_type}(stock/credit_risk/demand/customer/orderのいずれか)")

    # ---- auto_input: 設定(fields, screenType) ----
    async def _run_auto_input(self, config: dict, context: dict) -> tuple[dict, bool]:
        # 6.1節の設計原則(レガシー側はAI-Sync Bridgeの存在を知らない)により、実際のDOM入力は
        # Chrome拡張の content-script 側(auto-input-engine.js)が行う。サーバー側の役割は
        # フィールドの解決(テンプレート変数展開)までで、ここではその結果を返すに留める。
        return {
            "screen_type": config.get("screenType"),
            "fields": config.get("fields"),
            "note": "サーバー側はフィールド解決のみ実施。実際のDOM入力はChrome拡張のauto-input-engineが行う",
        }, True

    # ---- push: 設定(title, message, severity) ----
    async def _run_push(self, config: dict, context: dict) -> tuple[dict, bool]:
        severity = str(config.get("severity", "info")).lower()
        level = _SEVERITY_TO_LEVEL.get(severity, "info")
        notification = self.notification_center.push(
            source="workflow",
            level=level,
            title=config.get("title", "ワークフロー通知"),
            message=config.get("message", ""),
            ref_type="workflow",
            ref_id=None,
        )
        return notification, True

    # ---- recommend: 設定(tableName, recordId, maxResults) ----
    async def _run_recommend(self, config: dict, context: dict) -> tuple[dict, bool]:
        result = self.recommend_service.recommend(
            table_name=config.get("tableName"),
            record_id=int(config.get("recordId")),
            max_results=int(config.get("maxResults", 5)),
        )
        return result, True

    # ---- chat: 設定(systemPrompt, message) ----
    async def _run_chat(self, config: dict, context: dict) -> tuple[str, bool]:
        history = [{"role": "system", "content": config["systemPrompt"]}] if config.get("systemPrompt") else None
        reply = await self.ai.complete(config.get("message", ""), history=history)
        return reply, True

    # ---- wait: 設定(seconds) ----
    async def _run_wait(self, config: dict, context: dict) -> tuple[dict, bool]:
        seconds = min(float(config.get("seconds", 0) or 0), _WAIT_SECONDS_CAP)
        await asyncio.sleep(seconds)
        return {"waited_seconds": seconds}, True

    # ---- condition: 設定(variable, operator=[equals/contains/not_empty/empty], value) ----
    async def _run_condition(self, config: dict, context: dict) -> tuple[dict, bool]:
        variable = config.get("variable")
        operator = config.get("operator")
        if operator not in _CONDITION_OPERATORS:
            raise ValueError(f"未対応のoperator: {operator}(equals/contains/not_empty/emptyのいずれか)")
        raw = context.get(variable)
        expected = config.get("value")

        if operator == "equals":
            result = str(raw) == str(expected)
        elif operator == "contains":
            result = str(expected).lower() in str(raw).lower()
        elif operator == "not_empty":
            result = _truthy(raw)
        else:  # empty
            result = not _truthy(raw)

        output = {"variable": variable, "operator": operator, "raw_value": raw, "result": result}
        return output, result
