"""
インメモリ・デモデータストア（Singleton）
demo_mode=true のとき、実DBの代わりにプロセス内メモリで状態を保持する。
DIライフサイクル注意点: このクラスは Singleton。Scoped サービスから
毎回 new せず、必ず get_demo_store() 経由で同一インスタンスを参照すること。
（会話履歴やベクトルインデックスと同様、ここを誤ると状態が壊れる）
"""
from datetime import datetime
from functools import lru_cache
from threading import Lock


class DemoDataStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._next_id = 1
        self._next_order_id = 1
        self.customers: dict[int, dict] = {}
        self.orders: dict[int, dict] = {}
        self.chat_histories: dict[str, list[dict]] = {}
        self._seed()

    def _seed(self) -> None:
        seed_customers = [
            {"name": "山田太郎", "email": "yamada@example.com", "phone": "03-1234-5678", "company": "山田商事", "notes": "VIP顧客", "status": "取引中"},
            {"name": "佐藤花子", "email": "sato@example.com", "phone": "03-2345-6789", "company": "佐藤工業", "notes": "新規取引先", "status": "取引中"},
            {"name": "鈴木一郎", "email": "suzuki@example.com", "phone": "03-3456-7890", "company": "鈴木商店", "notes": "", "status": "休止"},
        ]
        for c in seed_customers:
            self.create_customer(c)

        # 予測分析/ワークフローのデモ用に受注履歴も併せてシードする(customer_id は上記作成順の1,2,3)。
        # 顧客1は右肩上がりの受注推移(売上予測トレンドのデモ)かつ直近発注ありで再受注リスクは
        # on_track、顧客2は due_soon、顧客3は休止顧客で大幅な overdue になるよう意図的に構成し、
        # 再受注予測の3段階(overdue/due_soon/on_track)を全て確認できるようにしている。
        seed_orders = [
            {"customer_id": 3, "item": "保守部品セット", "qty": 2, "amount": 150000, "date": "2025-11-01"},
            {"customer_id": 3, "item": "保守部品セット", "qty": 3, "amount": 200000, "date": "2026-01-05"},
            {"customer_id": 1, "item": "産業用ポンプ A-100", "qty": 3, "amount": 800000, "date": "2026-02-10"},
            {"customer_id": 1, "item": "産業用ポンプ A-100", "qty": 4, "amount": 950000, "date": "2026-03-12"},
            {"customer_id": 1, "item": "産業用ポンプ A-200", "qty": 4, "amount": 1100000, "date": "2026-04-15"},
            {"customer_id": 2, "item": "制御盤 CB-220", "qty": 2, "amount": 400000, "date": "2026-04-01"},
            {"customer_id": 1, "item": "産業用ポンプ A-200", "qty": 5, "amount": 1300000, "date": "2026-05-18"},
            {"customer_id": 2, "item": "制御盤 CB-220", "qty": 2, "amount": 420000, "date": "2026-05-05"},
            {"customer_id": 1, "item": "メンテナンス契約", "qty": 1, "amount": 1450000, "date": "2026-06-20"},
            {"customer_id": 2, "item": "制御盤 CB-330", "qty": 2, "amount": 450000, "date": "2026-06-25"},
            {"customer_id": 1, "item": "定期メンテナンス", "qty": 1, "amount": 500000, "date": "2026-07-20"},
        ]
        for o in seed_orders:
            self.create_order(o)

    # ---- Customer CRUD ----
    def create_customer(self, data: dict) -> dict:
        with self._lock:
            cid = self._next_id
            self._next_id += 1
            now = datetime.utcnow()
            record = {**data, "id": cid, "created_at": now, "updated_at": now}
            self.customers[cid] = record
            return record

    def list_customers(self) -> list[dict]:
        return list(self.customers.values())

    def get_customer(self, cid: int) -> dict | None:
        return self.customers.get(cid)

    def update_customer(self, cid: int, data: dict) -> dict | None:
        with self._lock:
            record = self.customers.get(cid)
            if not record:
                return None
            record.update({k: v for k, v in data.items() if v is not None})
            record["updated_at"] = datetime.utcnow()
            return record

    def delete_customer(self, cid: int) -> bool:
        with self._lock:
            return self.customers.pop(cid, None) is not None

    # ---- Order CRUD (予測分析/ワークフローエンジンが参照する) ----
    def create_order(self, data: dict) -> dict:
        with self._lock:
            oid = self._next_order_id
            self._next_order_id += 1
            record = {**data, "id": oid}
            self.orders[oid] = record
            return record

    def list_orders(self) -> list[dict]:
        return list(self.orders.values())

    def get_order(self, oid: int) -> dict | None:
        return self.orders.get(oid)

    def list_orders_by_customer(self, cid: int) -> list[dict]:
        return [o for o in self.orders.values() if o["customer_id"] == cid]

    # ---- Chat history (per session) ----
    def get_history(self, session_id: str) -> list[dict]:
        return self.chat_histories.setdefault(session_id, [])

    def append_history(self, session_id: str, role: str, content: str) -> None:
        self.get_history(session_id).append({"role": role, "content": content})

    # ---- Admin: デモデータ初期化 (Phase4) ----
    def reset(self) -> None:
        """顧客/受注/会話履歴を空にしてから再シードする。
        _seed() は create_customer/create_order 経由で自前ロックを取得するため、
        クリア処理のロック区間の外で呼び出す(Lock は再入不可のためデッドロックを避ける)。
        """
        with self._lock:
            self._next_id = 1
            self._next_order_id = 1
            self.customers.clear()
            self.orders.clear()
            self.chat_histories.clear()
        self._seed()


@lru_cache
def get_demo_store() -> DemoDataStore:
    """Singleton アクセサ。lru_cache によりプロセス内で1インスタンスのみ生成。"""
    return DemoDataStore()
