"""
DIライフサイクル定義
- Singleton: Settings, AiProvider, DemoDataStore(会話履歴/受注データ),
             VectorIndexManager(埋め込みキャッシュ/検索インデックス),
             WorkflowEngine(ルール定義/発火履歴・重複発火防止セット),
             NotificationCenter(通知一覧・既読状態), AuditLog(管理操作履歴)
- Scoped:    CustomerService, OrderService, ChatService, OcrService, SearchService,
             PredictiveService, AdminService (リクエスト毎に生成)
Singleton を Scoped 側で毎回 new すると、デモモードの会話状態・ベクトルインデックスの
再構築コスト・ワークフローの重複発火防止状態・通知の既読状態・監査ログ履歴が
壊れる/膨らむ/消えるため、必ず Depends 経由でこのモジュールの関数を使うこと。
"""
from functools import lru_cache

from app.config import Settings, get_settings
from app.services.ai_client import AiProvider, build_ai_provider
from app.services.admin_service import AdminService, AuditLog
from app.services.demo_data import DemoDataStore, get_demo_store
from app.services.customer_service import CustomerService
from app.services.order_service import OrderService
from app.services.chat_service import ChatService
from app.services.notification_service import NotificationCenter
from app.services.ocr_service import OcrService
from app.services.search_service import SearchService
from app.services.predictive_service import PredictiveService
from app.services.vector_index import VectorIndexManager
from app.services.workflow_service import WorkflowEngine
from app.services.nlsql_service import NLSQLService
from app.services.cross_analysis_service import CrossAnalysisService
from app.services.dynamic_analysis_service import DynamicAnalysisService


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


def get_chat_service() -> ChatService:
    return ChatService(get_ai_provider(), get_demo_store())


def get_ocr_service() -> OcrService:
    return OcrService(demo_mode=get_settings().demo_mode)


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
