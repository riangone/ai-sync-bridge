"""
DIライフサイクル定義
- Singleton: Settings, AiProvider, DemoDataStore(会話履歴/受注データ),
             VectorIndexManager(埋め込みキャッシュ/検索インデックス),
             WorkflowEngine(ルール定義/発火履歴・重複発火防止セット),
             NotificationCenter(通知一覧・既読状態), AuditLog(管理操作履歴)
- Scoped:    CustomerService, OrderService, ChatService, OcrService, SearchService,
             PredictiveService, AdminService, InventoryService, PurchaseOrderService,
             ProfitReportService, ArApService, PushService, AnalysisHistoryService,
             RecommendService, CompanySearchService, PropertySearchService,
             AssistantService, ConversationalInputService
             (リクエスト毎に生成)
Singleton を Scoped 側で毎回 new すると、デモモードの会話状態・ベクトルインデックスの
再構築コスト・ワークフローの重複発火防止状態・通知の既読状態・監査ログ履歴が
壊れる/膨らむ/消えるため、必ず Depends 経由でこのモジュールの関数を使うこと。
"""
from functools import lru_cache

from fastapi import HTTPException

from app.config import Settings, get_settings
from app.services.ai_client import AiProvider, build_ai_provider
from app.services.admin_service import AdminService, AuditLog
from app.services.demo_data import DemoDataStore, get_demo_store
from app.services.customer_service import CustomerService
from app.services.order_service import OrderService
from app.services.inventory_service import InventoryService
from app.services.purchase_order_service import PurchaseOrderService
from app.services.profit_report_service import ProfitReportService
from app.services.ar_ap_service import ArApService
from app.services.push_service import PushService
from app.services.analysis_history_service import AnalysisHistoryService
from app.services.recommend_service import RecommendService
from app.services.web_search_service import CompanySearchService, PropertySearchService
from app.services.chat_service import ChatService
from app.services.assistant_service import AssistantService
from app.services.conversational_input_service import ConversationalInputService
from app.services.notification_service import NotificationCenter
from app.services.ocr_service import OcrService
from app.services.search_service import SearchService
from app.services.predictive_service import PredictiveService
from app.services.vector_index import VectorIndexManager
from app.services.workflow_service import WorkflowEngine
from app.services.workflow_step_runner import WorkflowStepRunner
from app.services.nlsql_service import NLSQLService
from app.services.cross_analysis_service import CrossAnalysisService
from app.services.dynamic_analysis_service import DynamicAnalysisService
from app.services.realestate_advisory_service import RealestateAdvisoryService


@lru_cache
def get_ai_provider() -> AiProvider:
    return build_ai_provider(get_settings())


@lru_cache
def get_vector_index() -> VectorIndexManager:
    """Singleton: sqlite-vec -> ann -> brute-force を起動時に一度だけ解決する。"""
    return VectorIndexManager(get_settings().vector_backend)


@lru_cache
def get_workflow_engine() -> WorkflowEngine:
    """Singleton: ルール/発火履歴をプロセス全体で共有する(重複発火防止のため)。"""
    return WorkflowEngine()


@lru_cache
def get_notification_center() -> NotificationCenter:
    """Singleton: 既読/未読状態をプロセス全体で共有する。"""
    return NotificationCenter()


@lru_cache
def get_audit_log() -> AuditLog:
    """Singleton: 管理操作の監査ログをプロセス全体で共有する。"""
    return AuditLog()


# ---- Scoped factories (FastAPI Depends は関数呼び出し毎に実行される) ----
def get_customer_service() -> CustomerService:
    return CustomerService(get_settings(), get_demo_store())


def get_order_service() -> OrderService:
    return OrderService(get_settings(), get_demo_store())


def get_inventory_service() -> InventoryService:
    return InventoryService(get_settings(), get_demo_store())


def get_purchase_order_service() -> PurchaseOrderService:
    return PurchaseOrderService(get_settings(), get_demo_store())


def get_profit_report_service() -> ProfitReportService:
    return ProfitReportService(get_settings(), get_demo_store())


def get_ar_ap_service() -> ArApService:
    return ArApService(get_settings(), get_demo_store())


def get_push_service() -> PushService:
    """Inventory/ArApの異常検知結果を合成するため、両Scopedサービスを合わせて注入する。"""
    return PushService(get_settings(), get_demo_store(), get_inventory_service(), get_ar_ap_service())


def get_analysis_history_service() -> AnalysisHistoryService:
    return AnalysisHistoryService(get_settings(), get_demo_store())


def get_recommend_service() -> RecommendService:
    return RecommendService(get_settings(), get_demo_store())


def get_company_search_service() -> CompanySearchService:
    settings = get_settings()
    return CompanySearchService(demo_mode=settings.demo_mode, ai=get_ai_provider(), instance=settings.instance)


def get_property_search_service() -> PropertySearchService:
    # 物件検索は不動産(ERP)業態のみの機能。demo-legacy-system-dealer には Property
    # エンティティ自体が存在せず(整備/車検=ServiceOrderに置換済み)、対応する新規登録
    # フォームも無いため、register()の宛先を失った「見た目だけの機能」を残さないよう
    # instance="dealer"ではサービスを組み立てず、ここで明示的に404にする
    # (panel-web-search.js 側も同じ判定でタブ自体を出さないが、直接APIを叩かれた
    # 場合の防御としてサーバー側でも止める)。
    if get_settings().instance == "dealer":
        raise HTTPException(
            status_code=404,
            detail="この業態(自動車ディーラー)には物件検索機能はありません",
        )
    return PropertySearchService(demo_mode=get_settings().demo_mode, ai=get_ai_provider())


def get_chat_service() -> ChatService:
    return ChatService(get_ai_provider(), get_demo_store())


def get_assistant_service() -> AssistantService:
    return AssistantService(get_settings(), get_ai_provider(), get_demo_store())


def get_conversational_input_service() -> ConversationalInputService:
    return ConversationalInputService(get_settings(), get_ai_provider(), get_demo_store())


def get_ocr_service() -> OcrService:
    return OcrService(demo_mode=get_settings().demo_mode, ai=get_ai_provider(), instance=get_settings().instance)


def get_search_service() -> SearchService:
    return SearchService(get_ai_provider(), get_demo_store(), get_vector_index())


def get_predictive_service() -> PredictiveService:
    return PredictiveService(get_demo_store())


def get_admin_service() -> AdminService:
    return AdminService(
        get_settings(),
        get_demo_store(),
        get_workflow_engine(),
        get_notification_center(),
        get_audit_log(),
    )


def get_nlsql_service() -> NLSQLService:
    return NLSQLService(get_settings(), get_ai_provider())


def get_cross_analysis_service() -> CrossAnalysisService:
    return CrossAnalysisService(get_settings())


def get_dynamic_analysis_service() -> DynamicAnalysisService:
    return DynamicAnalysisService(get_settings(), get_ai_provider())


def get_realestate_advisory_service() -> RealestateAdvisoryService:
    """査定AI/仲介手数料上限チェック/内見重複検知は Property/Viewing エンティティに
    依存し、そもそも erp/dealer には該当エンティティが存在しない。
    get_property_search_service の instance=="dealer" 除外と同じ考え方で、
    instance != "realestate" ではサービスを組み立てず404にする。"""
    if get_settings().instance != "realestate":
        raise HTTPException(
            status_code=404,
            detail="この業態には不動産仲介向けアドバイザリー機能(査定/内見重複検知/仲介手数料チェック)はありません",
        )
    return RealestateAdvisoryService(get_settings())


def get_workflow_step_runner() -> WorkflowStepRunner:
    """Scoped: ワークフローの各ステップ(ocr/search/report/...)の実行を、既存の
    Scopedサービス群にそのまま委譲するための束ね役。WorkflowEngine自体はSingletonだが、
    このRunnerはリクエスト毎に組み立てる(内部で使うサービス群がScopedのため)。"""
    return WorkflowStepRunner(
        get_settings(),
        get_demo_store(),
        get_ai_provider(),
        get_ocr_service(),
        get_search_service(),
        get_recommend_service(),
        get_inventory_service(),
        get_predictive_service(),
        get_cross_analysis_service(),
        get_notification_center(),
    )
