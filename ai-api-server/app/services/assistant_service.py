"""
Business Assistant Service (Scoped)
実装ロードマップ Task#6: README 5.4.2「ビジネスアシスタント(BusinessAssistantService相当)」
= POST /api/local-ai/assist（panel-assistant.js が呼ぶ、画面コンテキストを認識する会話型AI）。

chat_service.py との違い: chat は単発の生メッセージをそのままAIへ渡すだけだが、
こちらは (1) 画面情報(screenType/url/title/formData)をシステムプロンプトに合成し、
(2) 会話履歴を最大20ターンで管理し、(3) 応答から「-」「*」始まりの行を
推奨アクションとして抽出する、という3点が上乗せされる。

会話履歴は chat_service と同じ DemoDataStore.chat_histories を間借りするが、
session_id を "assist:{conversationId}" というプレフィックス付きキーにして
/api/chat のセッションと名前空間が衝突しないようにしている。
"""
import re
import uuid

from app.config import Settings
from app.services.ai_client import AiProvider
from app.services.demo_data import DemoDataStore

_MAX_TURNS = 20  # 5.4.2: 「履歴に追加(最大20ターン、超過時は古いものから削除)」
_MAX_SUGGESTED_ACTIONS = 5

# 画面種別→日本語ラベル変換。screenType は panel-assistant.js の buildScreenContext()
# が `${detected.entity}/${detected.action}` (例: "Customer/Entry", "ServiceOrder/Detail")
# の形式で送ってくる(shared/dom-base.js の detectLegacyContext() 参照、entity は
# shared/config-base.js の LEGACY_ENTITIES.id、action は List/Entry/Detail/Search/
# Inquiry/Register)。旧実装は "order-input"等の非対応キーで待ち受けており実際には
# 一度もヒットしなかったため(2026-08-30 発覚)、instance分岐の導入と合わせて実際の
# 送信形式に合わせて修正した。entity側のラベルは instance(erp/dealer)で語彙が異なる
# ため辞書を分け、action側は共通(_ACTION_LABELS)。
_ACTION_LABELS = {
    "List": "一覧", "Entry": "登録/編集", "Detail": "詳細",
    "Search": "検索", "Inquiry": "照会", "Register": "登録",
}

# 各 demo-legacy-system(-dealer) の shared/config-base.js LEGACY_ENTITIES と対応
# (新エンティティ追加時は3箇所とも更新すること、既存の panels 定義coment と同じ運用)。
_ENTITY_LABELS_BY_INSTANCE = {
    "erp": {
        "Customer": "顧客", "Order": "受注", "Product": "商品/在庫", "Supplier": "仕入先",
        "Employee": "従業員", "Estimate": "見積", "Invoice": "請求", "PurchaseOrder": "発注",
        "InventoryTransaction": "在庫トランザクション", "GoodsReceipt": "入荷",
        "Property": "物件", "ArAp": "売掛買掛", "Profit": "利益",
    },
    "dealer": {
        "Customer": "顧客", "Order": "受注/契約", "Product": "車両在庫", "Supplier": "仕入先",
        "Employee": "従業員", "Estimate": "見積", "Invoice": "請求", "PurchaseOrder": "仕入",
        "InventoryTransaction": "車両入出庫", "GoodsReceipt": "入庫",
        "ServiceOrder": "整備/車検", "ArAp": "売掛買掛", "Profit": "利益",
    },
    "realestate": {
        "Customer": "顧客", "Order": "契約", "Property": "物件", "Supplier": "協力会社",
        "Employee": "担当エージェント", "Estimate": "査定", "Invoice": "請求",
        "PurchaseOrder": "工事発注", "InventoryTransaction": "物件ステータス履歴",
        "GoodsReceipt": "工事完了報告", "Viewing": "内見予約", "ArAp": "売掛買掛", "Profit": "利益",
    },
}

_FEATURES_BY_INSTANCE = {
    "erp": [
        "顧客/受注/在庫/発注の検索・登録", "OCRによる帳票読み取り・自動入力",
        "ベクトル検索・横断検索・自然言語検索", "需要予測・売上トレンド・与信リスク分析",
        "利益/粗利レポート・AR/APエイジング分析", "類似レコード推薦",
        "ワークフロー自動化(在庫アラート/OCR自動入力/与信超過チェック等)",
    ],
    "dealer": [
        "顧客/受注・契約/車両在庫/仕入の検索・登録", "OCRによる帳票読み取り・自動入力",
        "ベクトル検索・横断検索・自然言語検索", "需要予測・売上トレンド・与信リスク分析",
        "利益/粗利レポート・AR/APエイジング分析", "類似レコード推薦",
        "ワークフロー自動化(在庫アラート/OCR自動入力/与信超過チェック等)",
        "整備/車検の履歴照会・管理",
    ],
    "realestate": [
        "顧客/物件/契約・査定/協力会社の検索・登録", "OCRによる帳票読み取り・自動入力(物件概要書等)",
        "ベクトル検索・横断検索・自然言語検索", "成約予測・売上トレンド・ローン与信リスク分析",
        "仲介手数料/粗利レポート・AR/APエイジング分析", "類似物件推薦",
        "ワークフロー自動化(物件ステータスアラート/OCR自動入力/与信超過チェック等)",
        "内見予約の履歴照会・管理",
    ],
}

# ai-api-server自身のDemoDataStore(SQLite)テーブル名。instanceが変わってもテーブル
# スキーマ自体は共通(データの中身=シードのみがdealer/erpで分岐する)ため、
# こちらはinstance分岐しない(demo_data.py参照)。
_TABLE_NAMES = [
    "customers", "orders", "products", "purchase_orders",
    "invoices", "payables", "push_subscriptions", "analysis_history",
]


class AssistantService:
    def __init__(self, settings: Settings, ai: AiProvider, store: DemoDataStore):
        self.settings = settings
        self.ai = ai
        self.store = store

    @staticmethod
    def _history_key(conversation_id: str) -> str:
        return f"assist:{conversation_id}"

    def _screen_label(self, screen_type: str | None) -> str:
        if not screen_type:
            return "不明な画面"
        entity, _, action = screen_type.partition("/")
        entity_labels = _ENTITY_LABELS_BY_INSTANCE.get(
            self.settings.instance, _ENTITY_LABELS_BY_INSTANCE["erp"]
        )
        entity_label = entity_labels.get(entity)
        if entity_label is None:
            # 未知のentity(dashboard等、LEGACY_ENTITIESに無い screenType)はそのまま返す。
            return screen_type
        action_label = _ACTION_LABELS.get(action, action or "画面")
        return f"{entity_label}{action_label}画面"

    def _build_system_prompt(self, screen_context: dict | None) -> str:
        screen_context = screen_context or {}
        screen_type = screen_context.get("screen_type") or screen_context.get("screenType")
        features = _FEATURES_BY_INSTANCE.get(self.settings.instance, _FEATURES_BY_INSTANCE["erp"])
        lines = [
            "あなたは基幹システム「AI-Sync Bridge」の画面認識型ビジネスアシスタントです。",
            f"利用可能な機能: {', '.join(features)}",
            f"参照可能なデータテーブル: {', '.join(_TABLE_NAMES)}",
            "現在の画面情報:",
            f"  画面種別: {self._screen_label(screen_type)}({screen_type or '不明'})",
            f"  URL: {screen_context.get('url', '-')}",
            f"  タイトル: {screen_context.get('title', '-')}",
            f"  レコードID: {screen_context.get('record_id') or screen_context.get('recordId') or '-'}",
            f"  フォーム入力値: {screen_context.get('form_data') or screen_context.get('formData') or '-'}",
            "回答は簡潔に。ユーザーが次に取るべき行動があれば、行頭を「- 」で始めて箇条書きにすること(最大5件)。",
        ]
        return "\n".join(lines)

    @staticmethod
    def _extract_suggested_actions(text: str) -> list[str]:
        actions = []
        for line in text.splitlines():
            stripped = line.strip()
            if stripped.startswith("- ") or stripped.startswith("* "):
                actions.append(stripped[2:].strip())
            elif re.match(r"^[-*]\S", stripped):
                actions.append(stripped[1:].strip())
            if len(actions) >= _MAX_SUGGESTED_ACTIONS:
                break
        return actions

    async def assist(
        self,
        message: str,
        screen_context: dict | None = None,
        conversation_id: str | None = None,
    ) -> dict:
        conversation_id = conversation_id or uuid.uuid4().hex
        key = self._history_key(conversation_id)
        history = self.store.get_history(key)

        system_prompt = self._build_system_prompt(screen_context)
        prefixed_message = f"[画面コンテキスト付与済み]\n{message}"

        ai_history = [{"role": "system", "content": system_prompt}] + history
        reply = await self.ai.complete(prefixed_message, history=ai_history)

        self.store.append_history(key, "user", message)
        self.store.append_history(key, "assistant", reply)
        # 最大20ターン(=40メッセージ)を超えたら古いものから削除
        trimmed = history[-(_MAX_TURNS * 2):]
        history[:] = trimmed

        return {
            "response": reply,
            "conversation_id": conversation_id,
            "suggested_actions": self._extract_suggested_actions(reply),
            "provider": self.ai.name,
        }
