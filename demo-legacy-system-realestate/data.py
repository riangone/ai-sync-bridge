"""
デモ・レガシーシステム（不動産仲介版, localhost:5030） インメモリ「DB」
================================================================
demo-legacy-system（製造業向けERP）と同じ設計方針（7.1章 方式B: 独立インメモリ
ストア）を、日本の不動産仲介会社の基幹業務ドメインに置き換えたもの。
エンティティ構造・ヘルパー関数のシェイプは意図的に元ERPデモと揃えてあり、
main.py 側の汎用レンダリング処理（render_list/render_entry/render_detail/
entry_items.html の明細行グリッド）を無改造で再利用できるようにしている
（demo-legacy-system-dealer と同じフォーク方針）。

業務ドメイン対応表（元ERP → 不動産仲介）:
  Product（商品/在庫）     → 廃止。Property（物件）がOrder/Estimateの明細行
                              対象になる「商品」的ポジションを兼ねる
                              （元ERPのPropertyは独立マスタで受注/見積と未連携
                              だったのを接続し、本来あるべき「取扱不動産」の
                              位置づけに直した）
  Property（物件）         → 維持・拡張。Status（募集中/商談中/契約済/成約/
                              取り下げ）とOwnerId（売主=Customer）を追加し、
                              受注/見積の明細行対象として接続
  Order（受注）            → 契約（売買/賃貸契約）: Property 1件を明細行に持つ
  Estimate（見積）         → 査定（売却査定書）: Property 1件を明細行に持つ
  PurchaseOrder（発注）    → 工事発注: 協力会社（Supplier）へのリフォーム/
                              クリーニング等の発注。RENOVATION_SERVICES カタログ
                              を明細行対象にする（Propertyとは別カタログ）
  Supplier（仕入先）       → 協力会社: リフォーム/ハウスクリーニング/建物
                              インスペクション/引越し/損害保険代理店等
  Employee（従業員）       → 担当エージェント: 宅地建物取引士証番号を追加
  Invoice（請求）          → 仲介手数料請求
  GoodsReceipt（入荷）     → 工事完了報告: 協力会社＋対象物件の完了記録
  InventoryTransaction     → 物件ステータス履歴: 商品の入出庫ではなく、物件の
  （在庫トランザクション）    募集開始/内見受付/商談中/契約等のステータス変化ログ
  （新設）Viewing          → 内見予約: 不動産仲介特有の業務（元ERPには存在しない
                              エンティティを新規追加できることを示すデモも兼ねる。
                              dealerにおけるServiceOrder新設と同じ位置づけ）
"""
import os
import random
from datetime import datetime, timedelta

import sqlite_store

random.seed(42)

# ---------------------------------------------------------------------------
# 永続化(SQLite)
# ---------------------------------------------------------------------------
# demo-legacy-system-realestate専用のDBファイル。他のdemo-legacy-system*(別プロセス/
# 別ディレクトリ)とはファイルパスも接続オブジェクトも完全に分離しており、
# 互いのプロセスが起動していても一切干渉しない。
_DB_PATH = os.getenv("AISB_REALESTATE_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "realestate.db"))
_conn, _lock = sqlite_store.open_db(_DB_PATH)

# ---------------------------------------------------------------------------
# マスタ用の名称プール
# ---------------------------------------------------------------------------
PERSON_NAMES = [
    "山田太郎", "佐藤花子", "鈴木一郎", "高橋直美", "田中健太", "伊藤あゆみ",
    "渡辺修", "中村ゆり", "小林大輔", "加藤麻衣", "吉田誠", "山本裕子",
    "松本剛", "井上恵子", "木村隆", "林由美", "斎藤浩二", "清水香織",
]
COMPANY_CUSTOMER_NAMES = ["山田興産", "共同レジデンス", "中央アセットマネジメント"]
DEPARTMENTS = ["売買仲介部", "賃貸仲介部", "査定部", "管理部", "総務部"]
POSITIONS = ["部長", "課長", "主任エージェント", "エージェント", "アシスタント"]

PROPERTY_TYPES = ["マンション", "戸建て", "土地", "一棟収益"]
PROPERTY_NAME_STEMS = ["レジデンス丸の内", "パークハイツ梅田", "サンシャイン品川", "グリーンヒルズ横浜",
                        "セントラルタワー名古屋", "ベイサイド福岡", "ヒルサイド渋谷", "リバーサイド京都",
                        "アーバンコート恵比寿", "フォレストヒルズ吉祥寺"]
TRANSACTION_TYPES = ["専属専任媒介", "専任媒介", "一般媒介", "売主", "代理"]
PROPERTY_STATUSES = ["募集中", "商談中", "契約済", "成約", "取り下げ"]
STRUCTURES = ["RC造", "SRC造", "鉄骨造", "木造"]
LAND_RIGHTS = ["所有権", "定期借地権"]

SUPPLIER_NAMES = [
    "アーバンリフォーム", "クリーンパートナーズ", "住宅診断ラボ", "みらい引越センター",
    "総合損保代理店サンライズ", "解体・撤去 グリーンサービス", "内装工房匠", "設備テックワークス",
]
SUPPLIER_CATEGORIES = ["リフォーム", "ハウスクリーニング", "建物インスペクション", "引越し",
                        "損害保険代理店", "解体・残置物撤去"]

RENOVATION_SERVICES = [
    {"Id": "SV01", "Name": "ハウスクリーニング（一式）", "UnitPrice": 45000},
    {"Id": "SV02", "Name": "内装リフォーム（クロス張替）", "UnitPrice": 280000},
    {"Id": "SV03", "Name": "水回り設備交換", "UnitPrice": 650000},
    {"Id": "SV04", "Name": "外壁・屋根補修", "UnitPrice": 980000},
    {"Id": "SV05", "Name": "建物インスペクション（診断）", "UnitPrice": 55000},
    {"Id": "SV06", "Name": "残置物撤去", "UnitPrice": 120000},
    {"Id": "SV07", "Name": "シロアリ防除工事", "UnitPrice": 180000},
    {"Id": "SV08", "Name": "エアコン入替", "UnitPrice": 150000},
]

ORDER_STATUSES = ["商談中", "契約済", "引渡準備中", "引渡完了", "キャンセル"]
ESTIMATE_STATUSES = ["査定中", "提示済", "媒介契約締結", "失注"]
INVOICE_STATUSES = ["未回収", "入金済", "延滞"]
PO_STATUSES = ["発注中", "施工中", "完了", "キャンセル"]
PROPERTY_STATUS_HISTORY_TYPES = ["募集開始", "内見受付開始", "商談開始", "契約", "取り下げ"]
VIEWING_STATUSES = ["予約", "実施済", "キャンセル", "不成立"]


def _rand_date(min_days=-180, max_days=30):
    """base(今日)から見て [min_days, max_days] 日オフセットの日付を返す（負=過去/正=未来）。"""
    base = datetime(2026, 7, 25)
    delta = random.randint(min_days, max_days)
    return (base + timedelta(days=delta)).strftime("%Y-%m-%d")


def _postal():
    return f"{random.randint(100,999)}-{random.randint(1000,9999)}"


def _tel():
    return f"0{random.randint(1,9)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"


# ---------------------------------------------------------------------------
# Customers（顧客: 買主/売主）
# ---------------------------------------------------------------------------
customers = sqlite_store.PersistentDict(_conn, _lock, "customers")
if not customers:
    for i in range(1, 19):
        cid = f"C{i:04d}"
        is_corp = i % 7 == 0
        ctype = random.choice(["買主", "売主", "買主・売主"])
        limit = random.choice([3000000, 5000000, 8000000, 15000000, 30000000, 50000000])
        used = random.randint(0, limit)
        customers[cid] = {
            "Id": cid,
            "Name": COMPANY_CUSTOMER_NAMES[(i // 7 - 1) % len(COMPANY_CUSTOMER_NAMES)] if is_corp
                    else PERSON_NAMES[(i - 1) % len(PERSON_NAMES)],
            "NameKana": "カブシキガイシャ" if is_corp else "ヤマダタロウ",
            "CustomerType": ctype,
            "PostalCode": _postal(),
            "Address": f"東京都世田谷区北沢{random.randint(1,5)}-{random.randint(1,20)}-{random.randint(1,10)}",
            "Tel": _tel(),
            "Email": f"customer{i:03d}@example.co.jp",
            "DesiredArea": random.choice(["渋谷区", "港区", "世田谷区", "横浜市", "名古屋市", "指定なし"]),
            "Budget": random.choice([30000000, 45000000, 60000000, 80000000, 120000000]),
            "CreditLimit": limit,
            "CreditUsed": used,
            "Notes": "",
            "CreatedAt": _rand_date(-365, 0),
        }
customer_ids = list(customers.keys())

# ---------------------------------------------------------------------------
# Properties（物件） — 元ERPのProductに相当する「明細行の対象」を兼ねる
# ---------------------------------------------------------------------------
properties = sqlite_store.PersistentDict(_conn, _lock, "properties")
if not properties:
    for i in range(1, 15):
        pid = f"PR{i:03d}"
        name = PROPERTY_NAME_STEMS[(i - 1) % len(PROPERTY_NAME_STEMS)]
        ptype = PROPERTY_TYPES[(i - 1) % len(PROPERTY_TYPES)]
        owner = customers[random.choice(customer_ids)]
        properties[pid] = {
            "Id": pid,
            "Name": name if ptype != "土地" else f"{name} 分譲用地",
            "NameKana": "レジデンス",
            "PropertyType": ptype,
            "TransactionType": random.choice(TRANSACTION_TYPES),
            "OwnerId": owner["Id"],
            "OwnerName": owner["Name"],
            "Address": f"東京都港区南青山{random.randint(1,5)}-{random.randint(1,20)}-{random.randint(1,10)}",
            "Access": "東京メトロ表参道駅 徒歩8分",
            "LandArea": round(random.uniform(80, 500), 2),
            "BuildingArea": round(random.uniform(60, 400), 2) if ptype != "土地" else 0,
            "Structure": random.choice(STRUCTURES) if ptype != "土地" else "",
            "Floors": random.randint(1, 20) if ptype != "土地" else 0,
            "BuiltDate": _rand_date(-3650, -365) if ptype != "土地" else "",
            "LandRight": random.choice(LAND_RIGHTS),
            "Price": random.choice([28000000, 45000000, 68000000, 98000000, 150000000, 210000000]),
            "MonthlyRent": random.choice([80000, 120000, 180000, 250000]) if ptype != "土地" else 0,
            "Status": random.choice(PROPERTY_STATUSES),
            "OccupancyRate": round(random.uniform(70, 100), 2),
            "ParkingSpaces": random.randint(0, 20),
            "Facilities": "オートロック / 宅配ボックス / エレベーター",
            "CreatedAt": _rand_date(-365, 0),
        }
property_ids = list(properties.keys())


def property_catalog():
    """Order/Estimate の明細行ピッカー用アダプタ(Id/Name/UnitPriceの形に正規化)。"""
    return {p["Id"]: {"Id": p["Id"], "Name": p["Name"], "UnitPrice": p["Price"]} for p in properties.values()}


def renovation_catalog():
    return {s["Id"]: s for s in RENOVATION_SERVICES}


# ---------------------------------------------------------------------------
# Suppliers（協力会社） — リフォーム/クリーニング/インスペクション等
# ---------------------------------------------------------------------------
suppliers = sqlite_store.PersistentDict(_conn, _lock, "suppliers")
if not suppliers:
    for i in range(1, 9):
        sid = f"S{i:03d}"
        suppliers[sid] = {
            "Id": sid,
            "Name": SUPPLIER_NAMES[(i - 1) % len(SUPPLIER_NAMES)],
            "Category": SUPPLIER_CATEGORIES[(i - 1) % len(SUPPLIER_CATEGORIES)],
            "Tel": _tel(),
            "Address": f"大阪府大阪市北区梅田{random.randint(1,3)}-{random.randint(1,20)}",
            "ContactPerson": random.choice(PERSON_NAMES),
            "CreditAmount": random.choice([1000000, 3000000, 5000000, 10000000]),
            "PaymentTerms": random.choice(["月末締め翌月末払い", "月末締め翌々月10日払い", "工事完了都度払い"]),
            "Notes": "",
            "CreatedAt": _rand_date(-365, 0),
        }
supplier_ids = list(suppliers.keys())

# ---------------------------------------------------------------------------
# Employees（担当エージェント）
# ---------------------------------------------------------------------------
employees = sqlite_store.PersistentDict(_conn, _lock, "employees")
if not employees:
    for i in range(1, 12):
        eid = f"E{i:03d}"
        name = PERSON_NAMES[(i - 1) % len(PERSON_NAMES)]
        employees[eid] = {
            "Id": eid,
            "Name": name,
            "Department": random.choice(DEPARTMENTS),
            "Position": random.choice(POSITIONS),
            "LicenseNo": f"第{random.randint(10000,99999)}号" if random.random() > 0.2 else "",
            "Email": f"agent{i:03d}@realestate-legacy.example.co.jp",
            "Tel": _tel(),
            "HireDate": _rand_date(-3650, -365),
            "CreatedAt": _rand_date(-365, 0),
        }
employee_ids = list(employees.keys())

# ---------------------------------------------------------------------------
# Orders（契約: 売買/賃貸） + OrderItems（対象物件1件を明細行として保持）
# ---------------------------------------------------------------------------
orders = sqlite_store.PersistentDict(_conn, _lock, "orders")
order_items = sqlite_store.PersistentDict(_conn, _lock, "order_items")
if not orders:
    for i in range(1, 23):
        oid = f"ORD{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        prop = properties[random.choice(property_ids)]
        item = {"ProductId": prop["Id"], "ProductName": prop["Name"], "Quantity": 1,
                "UnitPrice": prop["Price"], "Amount": prop["Price"]}
        order_date = _rand_date(-180, 0)
        orders[oid] = {
            "Id": oid,
            "CustomerId": cust["Id"],
            "CustomerName": cust["Name"],
            "OrderDate": order_date,
            "DeliveryDate": _rand_date(-30, 60),
            "TotalAmount": item["Amount"],
            "Status": random.choice(ORDER_STATUSES),
            "Notes": "",
            "CreatedAt": order_date,
        }
        order_items[oid] = [item]

# ---------------------------------------------------------------------------
# Estimates（査定: 売却査定書） + EstimateItems
# ---------------------------------------------------------------------------
estimates = sqlite_store.PersistentDict(_conn, _lock, "estimates")
estimate_items = sqlite_store.PersistentDict(_conn, _lock, "estimate_items")
if not estimates:
    for i in range(1, 16):
        eid = f"EST{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        prop = properties[random.choice(property_ids)]
        # 査定額は物件価格の90〜105%程度でブレさせる(査定=見込み額であり成約額そのものではない)
        appraisal = round(prop["Price"] * random.uniform(0.90, 1.05) / 10000) * 10000
        item = {"ProductId": prop["Id"], "ProductName": prop["Name"], "Quantity": 1,
                "UnitPrice": appraisal, "Amount": appraisal}
        est_date = _rand_date(-120, 0)
        estimates[eid] = {
            "Id": eid,
            "CustomerId": cust["Id"],
            "CustomerName": cust["Name"],
            "EstimateDate": est_date,
            "ValidUntil": _rand_date(-60, 30),
            "TotalAmount": item["Amount"],
            "Status": random.choice(ESTIMATE_STATUSES),
            "Notes": "",
            "CreatedAt": est_date,
        }
        estimate_items[eid] = [item]

# ---------------------------------------------------------------------------
# PurchaseOrders（工事発注: 協力会社へのリフォーム/クリーニング等） + Items
# ---------------------------------------------------------------------------
purchase_orders = sqlite_store.PersistentDict(_conn, _lock, "purchase_orders")
purchase_order_items = sqlite_store.PersistentDict(_conn, _lock, "purchase_order_items")
if not purchase_orders:
    for i in range(1, 15):
        pid = f"PO{1000 + i}"
        sup = suppliers[random.choice(supplier_ids)]
        items = []
        for _ in range(random.randint(1, 3)):
            svc = random.choice(RENOVATION_SERVICES)
            qty = random.randint(1, 2)
            items.append({"ProductId": svc["Id"], "ProductName": svc["Name"], "Quantity": qty,
                          "UnitPrice": svc["UnitPrice"], "Amount": qty * svc["UnitPrice"]})
        total = sum(it["Amount"] for it in items)
        po_date = _rand_date(-150, 0)
        purchase_orders[pid] = {
            "Id": pid,
            "SupplierId": sup["Id"],
            "SupplierName": sup["Name"],
            "OrderDate": po_date,
            "DeliveryDate": _rand_date(-20, 45),
            "TotalAmount": total,
            "Status": random.choice(PO_STATUSES),
            "Notes": "",
            "CreatedAt": po_date,
        }
        purchase_order_items[pid] = items

# ---------------------------------------------------------------------------
# Invoices（仲介手数料請求・関連契約ベース）
# ---------------------------------------------------------------------------
invoices = sqlite_store.PersistentDict(_conn, _lock, "invoices")
order_id_list = list(orders.keys())
if not invoices:
    for i in range(1, 20):
        iid = f"INV{1000 + i}"
        order = orders[random.choice(order_id_list)]
        # 仲介手数料の簡易計算(宅建業法の速算式: 売買価格×3%+6万円、税別)を模したダミー額
        commission = round(order["TotalAmount"] * 0.03 + 60000)
        inv_date = _rand_date(-90, 0)
        invoices[iid] = {
            "Id": iid,
            "CustomerId": order["CustomerId"],
            "CustomerName": order["CustomerName"],
            "InvoiceDate": inv_date,
            "DueDate": _rand_date(-30, 30),
            "TotalAmount": commission,
            "Status": random.choice(INVOICE_STATUSES),
            "OrderId": order["Id"],
            "Notes": "仲介手数料(売買価格×3%+6万円 概算)",
            "CreatedAt": inv_date,
        }

# ---------------------------------------------------------------------------
# PropertyStatusHistory（物件ステータス履歴） — 元ERPのInventoryTransactionに相当
# ---------------------------------------------------------------------------
property_status_history = sqlite_store.PersistentList(_conn, _lock, "property_status_history")
if not property_status_history:
    for i in range(1, 43):
        pid = random.choice(property_ids)
        p = properties[pid]
        property_status_history.append({
            "Id": f"PH{i:05d}",
            "ProductId": pid,
            "ProductName": p["Name"],
            "Type": random.choice(PROPERTY_STATUS_HISTORY_TYPES),
            "Date": _rand_date(-180, 0),
            "Notes": "",
        })
# main.py 側は元ERPと同じ変数名(inventory_transactions)で参照するためのエイリアス。
inventory_transactions = property_status_history

# ---------------------------------------------------------------------------
# GoodsReceipt（工事完了報告） — 協力会社＋対象物件
# ---------------------------------------------------------------------------
goods_receipts = sqlite_store.PersistentDict(_conn, _lock, "goods_receipts")
if not goods_receipts:
    for i in range(1, 13):
        gid = f"GR{1000 + i}"
        sup = suppliers[random.choice(supplier_ids)]
        pid = random.choice(property_ids)
        p = properties[pid]
        goods_receipts[gid] = {
            "Id": gid,
            "SupplierId": sup["Id"],
            "SupplierName": sup["Name"],
            "PropertyId": pid,
            "PropertyName": p["Name"],
            "WorkDescription": random.choice(["ハウスクリーニング完了", "内装リフォーム完了",
                                                "建物インスペクション完了", "残置物撤去完了"]),
            "ReceiptDate": _rand_date(-90, 0),
        }

# ---------------------------------------------------------------------------
# Viewings（内見予約） — 不動産仲介特有の新設エンティティ
# ---------------------------------------------------------------------------
viewings = sqlite_store.PersistentDict(_conn, _lock, "viewings")
if not viewings:
    for i in range(1, 26):
        vid = f"VW{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        prop = properties[random.choice(property_ids)]
        agent = employees[random.choice(employee_ids)]
        viewings[vid] = {
            "Id": vid,
            "CustomerId": cust["Id"],
            "CustomerName": cust["Name"],
            "PropertyId": prop["Id"],
            "PropertyName": prop["Name"],
            "EmployeeId": agent["Id"],
            "EmployeeName": agent["Name"],
            "ViewingDate": _rand_date(-60, 30),
            "Status": random.choice(VIEWING_STATUSES),
            "Feedback": "",
            "CreatedAt": _rand_date(-60, 0),
        }

# ---------------------------------------------------------------------------
# ArAp（売掛買掛） — 顧客/協力会社ごとの残高を集計(元ERPと同一ロジック)
# ---------------------------------------------------------------------------
def build_arap():
    rows = []
    for c in customers.values():
        unpaid = sum(inv["TotalAmount"] for inv in invoices.values()
                     if inv["CustomerId"] == c["Id"] and inv["Status"] != "入金済")
        if unpaid > 0:
            rows.append({"Type": "売掛金(仲介手数料未収)", "PartnerName": c["Name"], "Balance": unpaid})
    for s in suppliers.values():
        unpaid = sum(po["TotalAmount"] for po in purchase_orders.values()
                     if po["SupplierId"] == s["Id"] and po["Status"] != "完了")
        if unpaid > 0:
            rows.append({"Type": "買掛金(協力会社未払い)", "PartnerName": s["Name"], "Balance": unpaid})
    return rows


# ---------------------------------------------------------------------------
# Profit（利益） — 物件別 仲介手数料収入/原価/粗利/粗利率
# ---------------------------------------------------------------------------
def build_profit():
    rows = []
    for pid, p in properties.items():
        sales = sum(it["Amount"] for items in order_items.values() for it in items if it["ProductId"] == pid)
        if sales == 0:
            continue
        cost = round(sales * random.uniform(0.55, 0.75))
        gross = sales - cost
        rate = round(gross / sales * 100, 1) if sales else 0
        rows.append({
            "ProductId": pid, "ProductName": p["Name"],
            "Sales": sales, "Cost": cost, "Gross": gross, "GrossRate": rate,
        })
    return sorted(rows, key=lambda r: -r["Sales"])


# ---------------------------------------------------------------------------
# ID採番（新規登録用）
# ---------------------------------------------------------------------------
_counters = {
    "Customer": len(customers), "Order": len(orders), "Estimate": len(estimates),
    "PurchaseOrder": len(purchase_orders), "Invoice": len(invoices),
    "Supplier": len(suppliers), "Employee": len(employees), "Property": len(properties),
    "GoodsReceipt": len(goods_receipts), "Viewing": len(viewings),
}
_ID_FORMATS = {
    "Customer": "C{:04d}", "Order": "ORD{:04d}", "Estimate": "EST{:04d}",
    "PurchaseOrder": "PO{:04d}", "Invoice": "INV{:04d}", "Supplier": "S{:03d}",
    "Employee": "E{:03d}", "Property": "PR{:03d}", "GoodsReceipt": "GR{:04d}",
    "Viewing": "VW{:04d}",
}


def next_id(entity: str) -> str:
    _counters[entity] += 1
    n = _counters[entity]
    fmt = _ID_FORMATS[entity]
    # ORD/EST/PO/INV/GR/VWは元データが1000番台始まりなので揃える
    if entity in ("Order", "Estimate", "PurchaseOrder", "Invoice", "GoodsReceipt", "Viewing"):
        return fmt.format(1000 + n)
    return fmt.format(n)
