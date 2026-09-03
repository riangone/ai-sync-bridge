"""
Analysis History Service (Scoped)
実装ロードマップ Phase4: README 5.3節 分析履歴系
(GET /api/analysis-history, POST /api/analysis-history)、
5.4.14「AnalysisHistoryService: 分析履歴のCRUD」。

NLSQL/クロス分析/予測分析/検索などAI分析系エンドポイントが返した「質問(query)→結果(result)」
の組を後から振り返れるように保存するだけの薄いCRUDサービス。各分析エンドポイント側からの
自動保存は行わない(README にも自動連携の記述はなく、既存エンドポイントのレスポンス形状を
変えたくないため) — Chrome拡張側がユーザー操作に応じて明示的にPOSTする設計。
"""
from app.config import Settings
from app.services.demo_data import DemoDataStore


class AnalysisHistoryService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store

    def list(self, type_: str | None = None, limit: int = 100) -> list[dict]:
        if self.settings.demo_mode:
            items = self.store.list_analysis_history()
            if type_:
                items = [i for i in items if i["type"] == type_]
            # 新しいものが先頭に来るよう降順(NotificationCenter.list()と同方針)。
            return list(reversed(items))[:limit]
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

    def create(self, type_: str, query: str, result: dict) -> dict:
        if self.settings.demo_mode:
            return self.store.create_analysis_history({"type": type_, "query": query, "result": result})
        raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")
