"""
Recommend Service (Scoped)
実装ロードマップ Phase2: README 5.3節「レコメンド系」(POST /api/recommend)、
4.3 panel-recommend.js: 画面のテーブルから選択した行データに類似する既存レコードを
一覧表示する。

predictive_service.py / purchase_order_service.py / ar_ap_service.py と同じ方針で、
外部AIプロバイダの embed() には依存しない(mock以外のプロバイダが未接続の環境でも
常に使えるようにするため)。類似度は文字bi-gram(2文字シングル)集合のJaccard係数で
計算する。日本語はスペース区切りの単語分割が機能しない(トークナイザ不要)ため、
言語非依存に効く文字n-gramシングリングを採用した(5.4.13 RandomProjectionIndexとは
独立した、テーブル横断の軽量アルゴリズム)。
includeExplanation=true の場合も外部AIは呼ばない。一致したフィールドを機械的に
文章化するだけで、push_service.py / ar_ap_service.py と同じ「ルールベース説明文」の
方針を踏襲する(フィールド名からも「AI」の語を外し、本物のAI解釈と混同されないように
している)。本物のAI解釈が欲しい場合は insight_service.interpret_recommend 経由の
GET /api/recommend/insight (完全にオプトイン)を使う。
"""
from app.config import Settings
from app.services.demo_data import DemoDataStore


def _customer_text(c: dict) -> str:
    return " ".join(str(v) for v in [c.get("name"), c.get("company"), c.get("notes"), c.get("status")] if v)


def _order_text(o: dict) -> str:
    return " ".join(str(v) for v in [o.get("item"), o.get("date")] if v)


def _product_text(p: dict) -> str:
    return " ".join(str(v) for v in [p.get("name"), p.get("sku"), p.get("supplier")] if v)


# tableName -> (DemoDataStoreからの一覧取得関数, テキスト化関数)
_TABLES: dict[str, tuple] = {
    "customers": (lambda store: store.list_customers(), _customer_text),
    "orders": (lambda store: store.list_orders(), _order_text),
    "products": (lambda store: store.list_products(), _product_text),
}


def _shingles(text: str, n: int = 2) -> set[str]:
    normalized = text.lower().replace(" ", "")
    if len(normalized) < n:
        return {normalized} if normalized else set()
    return {normalized[i:i + n] for i in range(len(normalized) - n + 1)}


def _jaccard(a: set[str], b: set[str]) -> float:
    if not a or not b:
        return 0.0
    union = len(a | b)
    return len(a & b) / union if union else 0.0


class RecommendService:
    def __init__(self, settings: Settings, store: DemoDataStore):
        self.settings = settings
        self.store = store

    def recommend(
        self,
        table_name: str,
        record_id: int,
        max_results: int = 5,
        include_explanation: bool = False,
    ) -> dict:
        if table_name not in _TABLES:
            raise ValueError(f"未対応のtableName: {table_name}(customers/orders/productsのいずれか)")
        if not self.settings.demo_mode:
            raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

        list_fn, text_fn = _TABLES[table_name]
        records = list_fn(self.store)
        by_id = {r["id"]: r for r in records}
        target = by_id.get(record_id)
        if target is None:
            raise KeyError(f"{table_name} に id={record_id} のレコードが見つかりません")

        target_shingles = _shingles(text_fn(target))
        scored = []
        for r in records:
            if r["id"] == record_id:
                continue
            score = _jaccard(target_shingles, _shingles(text_fn(r)))
            if score > 0:
                scored.append((score, r))
        scored.sort(key=lambda x: x[0], reverse=True)

        results = []
        for score, r in scored[:max_results]:
            entry = {"id": r["id"], "text": text_fn(r), "score": round(score, 4)}
            if include_explanation:
                entry["explanation"] = self._explain(target, r, table_name)
            results.append(entry)

        return {"table_name": table_name, "source_id": record_id, "results": results}

    @staticmethod
    def _explain(target: dict, other: dict, table_name: str) -> str:
        shared = []
        if table_name == "customers":
            if target.get("company") and target.get("company") == other.get("company"):
                shared.append(f"同じ取引先「{target['company']}」")
            if target.get("status") and target.get("status") == other.get("status"):
                shared.append(f"同じステータス「{target['status']}」")
        elif table_name == "orders":
            if target.get("item") and target.get("item") == other.get("item"):
                shared.append(f"同じ商品「{target['item']}」")
            if target.get("customer_id") == other.get("customer_id"):
                shared.append("同一顧客の受注")
        elif table_name == "products":
            if target.get("supplier") and target.get("supplier") == other.get("supplier"):
                shared.append(f"同じ仕入先「{target['supplier']}」")
        if shared:
            return "、".join(shared) + "という共通点があります。"
        return "テキスト内容が類似しています。"
