"""
SQLite永続化デモデータストア（Singleton）
demo_mode=true のとき、実DBの代わりにこのプロセス専用のSQLiteファイルで状態を
保持する(旧: プロセス内メモリのみ/再起動で消失 → 現在: 再起動をまたいで永続化)。
DIライフサイクル注意点: このクラスは Singleton。Scoped サービスから
毎回 new せず、必ず get_demo_store() 経由で同一インスタンスを参照すること。
（会話履歴やベクトルインデックスと同様、ここを誤ると状態が壊れる）

隔離性について: ai-api-server はERP版(port 5011)/ディーラー版(port 5021)を
「同一コードを2プロセス起動するだけ」で両業種に対応させている(業種非依存の
実証)。そのため各プロセスが同じSQLiteファイルを見てしまうと2つのデモが
互いのデータを上書きし合う。settings.db_path は settings.instance("erp"/
"dealer")ごとに既定で別ファイルになるため、env設定を忘れても物理的に分離される。
"""
import os
from datetime import datetime
from functools import lru_cache
from threading import Lock

from app.config import get_settings
from app.services import sqlite_store


class DemoDataStore:
    def __init__(self) -> None:
        self._lock = Lock()

        settings = get_settings()
        db_path = os.path.abspath(settings.db_path)
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._conn, self._db_lock = sqlite_store.open_db(db_path)

        def table(name: str) -> sqlite_store.PersistentDict:
            return sqlite_store.PersistentDict(self._conn, self._db_lock, name)

        self.customers: dict[int, dict] = table("customers")
        self.orders: dict[int, dict] = table("orders")
        # chat_historiesは非永続(意図的): setdefault/list.append経由の更新はdictの
        # C実装がPersistentDict.__setitem__をバイパスするためwrite-throughできず、
        # 中途半端に持たせると「たまに消える」壊れた永続化に見える方が害が大きい。
        # WorkflowEngine/NotificationCenter/AuditLog(deps.py参照)と同様、会話の
        # 生存状態はプロセス内メモリのSingletonのままでよい設計判断。
        self.chat_histories: dict[str, list[dict]] = {}
        # Phase4: 在庫/発注(README 9章 Phase4「PurchaseOrderController + InventoryController」)
        self.products: dict[int, dict] = table("products")
        self.purchase_orders: dict[int, dict] = table("purchase_orders")
        # Phase4: 売掛/買掛(README 9章 Phase4「ArApController + ProfitReportController」)
        # invoices=売掛金(顧客への請求), payables=買掛金(仕入先への未払). ArApService.aging() が
        # due_date と本日日付の差分からエイジングバケット(current/1-30/31-60/61-90/90+)を算出する。
        self.invoices: dict[int, dict] = table("invoices")
        self.payables: dict[int, dict] = table("payables")
        # Phase4: プッシュ購読/分析履歴(README 9章 Phase4「PushController + AlertCheckService」
        # 7.2節 PushSubscriptionsテーブル)。どちらもユーザー操作から動的に生成される状態であり
        # notifications(NotificationCenter)と同様、初期シードは行わない。
        self.push_subscriptions: dict[int, dict] = table("push_subscriptions")
        self.analysis_history: dict[int, dict] = table("analysis_history")

        # 既存のSQLiteファイルから読み込めた場合はID採番をその続きから再開する
        # (再起動のたびに1から採番し直すとキー衝突/上書きが起きるため)。
        self._next_id = max(self.customers.keys(), default=0) + 1
        self._next_order_id = max(self.orders.keys(), default=0) + 1
        self._next_product_id = max(self.products.keys(), default=0) + 1
        self._next_po_id = max(self.purchase_orders.keys(), default=0) + 1
        self._next_invoice_id = max(self.invoices.keys(), default=0) + 1
        self._next_payable_id = max(self.payables.keys(), default=0) + 1
        self._next_subscription_id = max(self.push_subscriptions.keys(), default=0) + 1
        self._next_history_id = max(self.analysis_history.keys(), default=0) + 1

        # 空(=初回起動、またはDBファイルなし)のときだけシードする。2回目以降の
        # 起動はSQLiteから読み込んだ状態(CRUD操作の結果を含む)をそのまま使う。
        if not self.customers:
            self._seed()

    def _seed(self) -> None:
        """settings.instance("erp"/"dealer")に応じてシードデータを切り替える。
        ai-api-server は同一コードをERP版/ディーラー版の2プロセスとして動かす構成
        (業種非依存の実証)だが、ダミーデータの世界観までERP風("山田商事"等)の
        ままだと、ディーラー版のAIチャット/類似検索/ワークフローが実際の車両在庫
        (demo-legacy-system-dealer側)と食い違って見える。instanceで切り替えることで
        両インスタンスの見た目上の一貫性を揃える。
        """
        if get_settings().instance == "dealer":
            self._seed_dealer()
        else:
            self._seed_erp()

    def _seed_erp(self) -> None:
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

        # 在庫AI分析/異常検知(reorder_point割れ)と発注AI提案のデモ用シード。
        # ポンプA-100/A-200は上記受注シードで頻繁に出るため、意図的にreorder_point割れ
        # (stock < reorder_point)にして異常検知パネルで即座に検出できるようにしている。
        seed_products = [
            {"name": "産業用ポンプ A-100", "sku": "PUMP-A100", "stock": 4, "reorder_point": 10, "unit_cost": 180000, "supplier": "山田商事"},
            {"name": "産業用ポンプ A-200", "sku": "PUMP-A200", "stock": 2, "reorder_point": 8, "unit_cost": 220000, "supplier": "佐藤工業"},
            {"name": "制御盤 CB-220", "sku": "CTRL-CB220", "stock": 25, "reorder_point": 6, "unit_cost": 150000, "supplier": "佐藤工業"},
            {"name": "制御盤 CB-330", "sku": "CTRL-CB330", "stock": 12, "reorder_point": 5, "unit_cost": 170000, "supplier": "鈴木商店"},
            {"name": "保守部品セット", "sku": "MAINT-KIT", "stock": 3, "reorder_point": 15, "unit_cost": 45000, "supplier": "鈴木商店"},
        ]
        for p in seed_products:
            self.create_product(p)

        seed_pos = [
            {"product_id": 1, "supplier": "山田商事", "qty": 10, "status": "received", "ordered_at": "2026-06-01", "expected_date": "2026-06-15", "received_qty": 10, "received_at": "2026-06-14"},
            {"product_id": 2, "supplier": "佐藤工業", "qty": 6, "status": "ordered", "ordered_at": "2026-08-01", "expected_date": "2026-08-20", "received_qty": 0},
        ]
        for po in seed_pos:
            self.create_purchase_order(po)

        # AR/APエイジング分析のデモ用シード(実行時の本日日付との差分でバケットが決まるため、
        # 意図的に「未到来/1-30/31-60/61-90/90+/支払済(除外対象)」を一通り作っている)。
        # 日付は seed_orders/seed_products と同じ架空タイムライン(2026年)に揃えている。
        seed_invoices = [
            {"customer_id": 1, "amount": 800000, "issued_at": "2026-07-25", "due_date": "2026-08-24"},
            {"customer_id": 1, "amount": 950000, "issued_at": "2026-06-10", "due_date": "2026-07-10"},
            {"customer_id": 2, "amount": 400000, "issued_at": "2026-05-01", "due_date": "2026-05-31"},
            {"customer_id": 2, "amount": 420000, "issued_at": "2026-03-01", "due_date": "2026-03-31"},
            {"customer_id": 3, "amount": 150000, "issued_at": "2026-07-01", "due_date": "2026-07-31"},
            {"customer_id": 3, "amount": 200000, "issued_at": "2026-01-05", "due_date": "2026-02-04",
             "paid": True, "paid_at": "2026-02-01"},
        ]
        for inv in seed_invoices:
            self.create_invoice(inv)

        seed_payables = [
            {"supplier": "山田商事", "amount": 1800000, "issued_at": "2026-06-15", "due_date": "2026-07-15"},
            {"supplier": "佐藤工業", "amount": 1320000, "issued_at": "2026-08-05", "due_date": "2026-09-04"},
            {"supplier": "鈴木商店", "amount": 270000, "issued_at": "2026-04-01", "due_date": "2026-05-01"},
            {"supplier": "佐藤工業", "amount": 900000, "issued_at": "2026-02-01", "due_date": "2026-03-03",
             "paid": True, "paid_at": "2026-02-28"},
        ]
        for pay in seed_payables:
            self.create_payable(pay)

    def _seed_dealer(self) -> None:
        """自動車ディーラー版(AISB_INSTANCE=dealer)向けシード。demo-legacy-system-dealer
        (port 5020)と用語・登場人物を揃えている(顧客=個人/運送会社、商品=車両、
        仕入先=オークション会場)。件数・日付構成は_seed_erp()と意図的に揃えており、
        予測分析(on_track/due_soon/overdue)やAR/APエイジングのデモ挙動は同一。
        """
        seed_customers = [
            {"name": "山田太郎", "email": "yamada@example.com", "phone": "03-1234-5678", "company": "", "notes": "VIP顧客(個人)", "status": "取引中"},
            {"name": "佐藤花子", "email": "sato@example.com", "phone": "03-2345-6789", "company": "共同タクシー", "notes": "法人(社用車まとめ購入)", "status": "取引中"},
            {"name": "鈴木一郎", "email": "suzuki@example.com", "phone": "03-3456-7890", "company": "", "notes": "", "status": "休止"},
        ]
        for c in seed_customers:
            self.create_customer(c)

        seed_orders = [
            {"customer_id": 3, "item": "オイル交換パック", "qty": 2, "amount": 15000, "date": "2025-11-01"},
            {"customer_id": 3, "item": "オイル交換パック", "qty": 3, "amount": 20000, "date": "2026-01-05"},
            {"customer_id": 1, "item": "トヨタ カローラ G", "qty": 1, "amount": 2100000, "date": "2026-02-10"},
            {"customer_id": 1, "item": "トヨタ ハリアー S", "qty": 1, "amount": 2980000, "date": "2026-03-12"},
            {"customer_id": 1, "item": "車検整備", "qty": 1, "amount": 110000, "date": "2026-04-15"},
            {"customer_id": 2, "item": "日産 セレナ ハイブリッドG", "qty": 2, "amount": 4200000, "date": "2026-04-01"},
            {"customer_id": 1, "item": "オプション用品セット", "qty": 4, "amount": 130000, "date": "2026-05-18"},
            {"customer_id": 2, "item": "日産 セレナ ハイブリッドG", "qty": 2, "amount": 4200000, "date": "2026-05-05"},
            {"customer_id": 1, "item": "点検整備契約", "qty": 1, "amount": 145000, "date": "2026-06-20"},
            {"customer_id": 2, "item": "法定12ヶ月点検", "qty": 2, "amount": 45000, "date": "2026-06-25"},
            {"customer_id": 1, "item": "定期点検", "qty": 1, "amount": 50000, "date": "2026-07-20"},
        ]
        for o in seed_orders:
            self.create_order(o)

        # 在庫AI分析/異常検知(reorder_point割れ)のデモ用シード。人気車種を意図的に
        # 品薄(stock < reorder_point)にしている。
        seed_products = [
            {"name": "トヨタ カローラ G", "sku": "VEH-COROLLA-G", "stock": 1, "reorder_point": 3, "unit_cost": 1800000, "supplier": "トヨタ卸販売"},
            {"name": "トヨタ ハリアー S", "sku": "VEH-HARRIER-S", "stock": 0, "reorder_point": 2, "unit_cost": 2500000, "supplier": "USS東京オークション"},
            {"name": "日産 セレナ ハイブリッドG", "sku": "VEH-SERENA-HG", "stock": 5, "reorder_point": 2, "unit_cost": 3500000, "supplier": "日産ディーラー卸"},
            {"name": "ホンダ フィット", "sku": "VEH-FIT", "stock": 3, "reorder_point": 1, "unit_cost": 1300000, "supplier": "ホンダカーズ卸部門"},
            {"name": "スズキ ハスラー", "sku": "VEH-HUSTLER", "stock": 1, "reorder_point": 4, "unit_cost": 1100000, "supplier": "全国下取りネットワーク"},
        ]
        for p in seed_products:
            self.create_product(p)

        seed_pos = [
            {"product_id": 1, "supplier": "トヨタ卸販売", "qty": 3, "status": "received", "ordered_at": "2026-06-01", "expected_date": "2026-06-15", "received_qty": 3, "received_at": "2026-06-14"},
            {"product_id": 2, "supplier": "USS東京オークション", "qty": 2, "status": "ordered", "ordered_at": "2026-08-01", "expected_date": "2026-08-20", "received_qty": 0},
        ]
        for po in seed_pos:
            self.create_purchase_order(po)

        seed_invoices = [
            {"customer_id": 1, "amount": 2100000, "issued_at": "2026-07-25", "due_date": "2026-08-24"},
            {"customer_id": 1, "amount": 2980000, "issued_at": "2026-06-10", "due_date": "2026-07-10"},
            {"customer_id": 2, "amount": 4200000, "issued_at": "2026-05-01", "due_date": "2026-05-31"},
            {"customer_id": 2, "amount": 4200000, "issued_at": "2026-03-01", "due_date": "2026-03-31"},
            {"customer_id": 3, "amount": 15000, "issued_at": "2026-07-01", "due_date": "2026-07-31"},
            {"customer_id": 3, "amount": 20000, "issued_at": "2026-01-05", "due_date": "2026-02-04",
             "paid": True, "paid_at": "2026-02-01"},
        ]
        for inv in seed_invoices:
            self.create_invoice(inv)

        seed_payables = [
            {"supplier": "トヨタ卸販売", "amount": 5400000, "issued_at": "2026-06-15", "due_date": "2026-07-15"},
            {"supplier": "USS東京オークション", "amount": 5000000, "issued_at": "2026-08-05", "due_date": "2026-09-04"},
            {"supplier": "日産ディーラー卸", "amount": 3500000, "issued_at": "2026-04-01", "due_date": "2026-05-01"},
            {"supplier": "USS東京オークション", "amount": 2600000, "issued_at": "2026-02-01", "due_date": "2026-03-03",
             "paid": True, "paid_at": "2026-02-28"},
        ]
        for pay in seed_payables:
            self.create_payable(pay)

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
            self.customers[cid] = record  # SQLite永続化(インプレース変更はwrite-throughされないため再代入)
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

    # ---- Product / Inventory CRUD (Phase4: 在庫AI分析・異常検知が参照する) ----
    def create_product(self, data: dict) -> dict:
        with self._lock:
            pid = self._next_product_id
            self._next_product_id += 1
            record = {**data, "id": pid}
            self.products[pid] = record
            return record

    def list_products(self) -> list[dict]:
        return list(self.products.values())

    def get_product(self, pid: int) -> dict | None:
        return self.products.get(pid)

    def update_product(self, pid: int, data: dict) -> dict | None:
        with self._lock:
            record = self.products.get(pid)
            if not record:
                return None
            record.update({k: v for k, v in data.items() if v is not None})
            self.products[pid] = record  # SQLite永続化(インプレース変更はwrite-throughされないため再代入)
            return record

    def adjust_stock(self, pid: int, delta: int) -> dict | None:
        """入荷登録(goods-receipt)/出荷等で在庫数を増減する。マイナス在庫は許容しない。"""
        with self._lock:
            record = self.products.get(pid)
            if not record:
                return None
            record["stock"] = max(0, record.get("stock", 0) + delta)
            self.products[pid] = record  # SQLite永続化(インプレース変更はwrite-throughされないため再代入)
            return record

    # ---- Purchase Order CRUD (Phase4: 発注管理AI提案・仕入先評価が参照する) ----
    def create_purchase_order(self, data: dict) -> dict:
        with self._lock:
            oid = self._next_po_id
            self._next_po_id += 1
            record = {"status": "ordered", "received_qty": 0, **data, "id": oid}
            self.purchase_orders[oid] = record
            return record

    def list_purchase_orders(self) -> list[dict]:
        return list(self.purchase_orders.values())

    def get_purchase_order(self, poid: int) -> dict | None:
        return self.purchase_orders.get(poid)

    def update_purchase_order(self, poid: int, data: dict) -> dict | None:
        with self._lock:
            record = self.purchase_orders.get(poid)
            if not record:
                return None
            record.update({k: v for k, v in data.items() if v is not None})
            self.purchase_orders[poid] = record  # SQLite永続化(インプレース変更はwrite-throughされないため再代入)
            return record

    # ---- Invoice CRUD (Phase4: 売掛金/AR。ArApService.aging() が参照する) ----
    def create_invoice(self, data: dict) -> dict:
        with self._lock:
            iid = self._next_invoice_id
            self._next_invoice_id += 1
            record = {"paid": False, "paid_at": None, **data, "id": iid}
            self.invoices[iid] = record
            return record

    def list_invoices(self) -> list[dict]:
        return list(self.invoices.values())

    # ---- Payable CRUD (Phase4: 買掛金/AP。ArApService.aging() が参照する) ----
    def create_payable(self, data: dict) -> dict:
        with self._lock:
            pid = self._next_payable_id
            self._next_payable_id += 1
            record = {"paid": False, "paid_at": None, **data, "id": pid}
            self.payables[pid] = record
            return record

    def list_payables(self) -> list[dict]:
        return list(self.payables.values())

    # ---- Push Subscription CRUD (Phase4: PushService.subscribe/unsubscribe/list が参照する) ----
    def upsert_push_subscription(self, data: dict) -> dict:
        """endpoint(Web Push仕様上ブラウザ購読ごとに一意)が既存なら鍵情報を更新し、
        なければ新規作成する。同一デバイスの再購読で購読が重複増殖するのを防ぐ。
        """
        with self._lock:
            for sid, record in self.push_subscriptions.items():
                if record["endpoint"] == data["endpoint"]:
                    record.update({k: v for k, v in data.items() if v is not None})
                    self.push_subscriptions[sid] = record  # SQLite永続化(インプレース変更は再代入が必要)
                    return record
            sid = self._next_subscription_id
            self._next_subscription_id += 1
            record = {**data, "id": sid, "created_at": datetime.utcnow()}
            self.push_subscriptions[sid] = record
            return record

    def list_push_subscriptions(self) -> list[dict]:
        return list(self.push_subscriptions.values())

    def delete_push_subscription(self, endpoint: str) -> bool:
        with self._lock:
            for sid, record in list(self.push_subscriptions.items()):
                if record["endpoint"] == endpoint:
                    del self.push_subscriptions[sid]
                    return True
            return False

    # ---- Analysis History CRUD (Phase4: AnalysisHistoryService が参照する) ----
    def create_analysis_history(self, data: dict) -> dict:
        with self._lock:
            hid = self._next_history_id
            self._next_history_id += 1
            record = {**data, "id": hid, "created_at": datetime.utcnow()}
            self.analysis_history[hid] = record
            return record

    def list_analysis_history(self) -> list[dict]:
        return list(self.analysis_history.values())

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
            self._next_product_id = 1
            self._next_po_id = 1
            self._next_invoice_id = 1
            self._next_payable_id = 1
            self._next_subscription_id = 1
            self._next_history_id = 1
            self.customers.clear()
            self.orders.clear()
            self.chat_histories.clear()
            self.products.clear()
            self.purchase_orders.clear()
            self.invoices.clear()
            self.payables.clear()
            self.push_subscriptions.clear()
            self.analysis_history.clear()
        self._seed()


@lru_cache
def get_demo_store() -> DemoDataStore:
    """Singleton アクセサ。lru_cache によりプロセス内で1インスタンスのみ生成。"""
    return DemoDataStore()
