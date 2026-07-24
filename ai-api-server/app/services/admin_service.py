"""
Admin Service (Scoped) + AuditLog (Singleton)
実装ロードマップ Phase4 ③: システム統計の可視化・管理操作の監査ログ・
デモデータの初期化をまとめる管理者向けサービス。

AuditLog は Singleton。管理操作の履歴をプロセス全体で共有する必要があるため、
Scoped で毎回 new すると履歴が消える(NotificationCenter/WorkflowEngineと同種のDI設計)。
AdminService 自体は他の Scoped サービス群と同じく毎リクエスト生成でよい
(内部で保持するのは Singleton への参照のみで、状態そのものは持たない)。
"""
from datetime import datetime
from threading import Lock

from app.config import Settings
from app.services.demo_data import DemoDataStore
from app.services.notification_service import NotificationCenter
from app.services.workflow_service import WorkflowEngine


class AuditLog:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = 1
        self.entries: list[dict] = []

    def record(self, actor: str, action: str, detail: str) -> dict:
        with self._lock:
            entry = {
                "id": self._next_id,
                "actor": actor,
                "action": action,
                "detail": detail,
                "at": datetime.utcnow(),
            }
            self._next_id += 1
            self.entries.append(entry)
            return entry

    def list(self, limit: int = 100) -> list[dict]:
        return list(reversed(self.entries))[:limit]


class AdminService:
    def __init__(
        self,
        settings: Settings,
        store: DemoDataStore,
        workflow_engine: WorkflowEngine,
        notifications: NotificationCenter,
        audit_log: AuditLog,
    ) -> None:
        self.settings = settings
        self.store = store
        self.workflow_engine = workflow_engine
        self.notifications = notifications
        self.audit_log = audit_log

    def stats(self) -> dict:
        return {
            "demo_mode": self.settings.demo_mode,
            "ai_provider": self.settings.ai_provider,
            "vector_backend": self.settings.vector_backend,
            "customer_count": len(self.store.list_customers()),
            "order_count": len(self.store.list_orders()),
            "workflow_rule_count": len(self.workflow_engine.list_rules()),
            "workflow_event_count": len(self.workflow_engine.history),
            "unread_notification_count": self.notifications.unread_count(),
            "generated_at": datetime.utcnow(),
        }

    def reset_demo_data(self, actor: str = "admin") -> dict:
        """demo_mode=true のインメモリデータを初期シード状態へ戻す。
        本番DB接続時はこの操作自体を提供しない(誤って実データを消さないため)。
        """
        if not self.settings.demo_mode:
            raise NotImplementedError("demo_mode=false では提供しない管理操作です")
        self.store.reset()
        # 顧客/受注のIDが振り直されるため、重複発火防止セットも合わせてリセットしないと
        # 新しいエンティティが古いIDと衝突して「再発火しない」バグになる。
        self.workflow_engine.reset()
        self.audit_log.record(actor, "reset_demo_data", "デモデータ(顧客/受注/会話履歴)を初期状態にリセットしました")
        self.notifications.push(
            source="admin",
            level="warning",
            title="デモデータをリセットしました",
            message="顧客/受注データと会話履歴が初期シード状態に戻されました",
        )
        return self.stats()
