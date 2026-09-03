"""
デモ・レガシーシステム インメモリ「DB」
====================================
実DBを持たない代わりに、7.1章のDBスキーマ（Customers/Orders/OrderItems/...）に
準拠した構造をそのままPythonのdictで保持する（方式B: 独立インメモリストア）。

ai-api-server 側の demo_data.py とはプロセスが分離しているため同一データではないが、
同じ業務ドメイン・同じ日本語ダミーデータの作法で用意し、見た目上の一貫性を保つ。
"""
import os
import random
from datetime import datetime, timedelta

import sqlite_store

random.seed(42)

# ---------------------------------------------------------------------------
# 永続化(SQLite)
# ---------------------------------------------------------------------------
# demo-legacy-system専用のDBファイル。demo-legacy-system-dealer(別プロセス/別
# ディレクトリ)とはファイルパスも接続オブジェクトも完全に分離しており、
# 互いのプロセスが起動していても一切干渉しない。
_DB_PATH = os.getenv("AISB_ERP_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "erp.db"))
_conn, _lock = sqlite_store.open_db(_DB_PATH)

# ---------------------------------------------------------------------------
# マスタ用の名称プール
# ---------------------------------------------------------------------------
COMPANY_NAMES = [
    "山田商事", "佐藤工業", "鈴木商店", "高橋物産", "田中興産", "伊藤製作所",
    "渡辺electronics", "中村建設", "小林運輸", "加藤商会", "吉田フーズ",
    "山本テクノ", "松本金属", "井上化学", "木村通商", "林精密工業",
    "斎藤エンジニアリング", "清水商事", "山口食品", "森田工務店",
]
PERSON_NAMES = [
    "山田太郎", "佐藤花子", "鈴木一郎", "高橋直美", "田中健太", "伊藤あゆみ",
    "渡辺修", "中村ゆり", "小林大輔", "加藤麻衣", "吉田誠", "山本裕子",
    "松本剛", "井上恵子", "木村隆", "林由美", "斎藤浩二", "清水香織",
]
DEPARTMENTS = ["営業部", "総務部", "経理部", "製造部", "資材部", "情報システム部", "人事部"]
POSITIONS = ["部長", "課長", "係長", "主任", "一般社員"]
PRODUCT_CATEGORIES = ["機械部品", "電子部品", "工具", "消耗品", "梱包資材", "安全用品"]
PRODUCT_NAME_STEMS = [
    "産業用ポンプ", "制御盤", "サーボモーター", "軸受ユニット", "油圧シリンダー",
    "センサーユニット", "配電盤", "コンベアベルト", "断熱材", "溶接ワイヤー",
    "安全ヘルメット", "防護手袋", "梱包用フィルム", "工具セット", "計測器",
]
ORDER_STATUSES = ["確認中", "製造中", "出荷済", "納品完了", "キャンセル"]
ESTIMATE_STATUSES = ["作成中", "提示済", "承認", "失注"]
INVOICE_STATUSES = ["未払い", "入金済", "延滞"]
PO_STATUSES = ["発注中", "入荷済", "キャンセル"]


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
# Customers
# ---------------------------------------------------------------------------
customers = sqlite_store.PersistentDict(_conn, _lock, "customers")
if not customers:
    for i in range(1, 17):
        cid = f"C{i:04d}"
        limit = random.choice([500000, 1000000, 2000000, 3000000, 5000000])
        used = random.randint(0, limit)
        customers[cid] = {
            "Id": cid,
            "Name": COMPANY_NAMES[(i - 1) % len(COMPANY_NAMES)],
            "NameKana": "カブシキガイシャ" + COMPANY_NAMES[(i - 1) % len(COMPANY_NAMES)][:2],
            "Representative": random.choice(PERSON_NAMES),
            "PostalCode": _postal(),
            "Address": f"東京都千代田区丸の内{random.randint(1,3)}-{random.randint(1,20)}-{random.randint(1,10)}",
            "Tel": _tel(),
            "Fax": _tel(),
            "Website": f"https://www.example-{i}.co.jp",
            "Capital": random.choice([1000000, 5000000, 10000000, 30000000, 50000000]),
            "Employees": random.randint(5, 500),
            "Industry": random.choice(["製造業", "卸売業", "小売業", "建設業", "サービス業"]),
            "CreditLimit": limit,
            "CreditUsed": used,
            "Notes": "",
            "CreatedAt": _rand_date(-365, 0),
        }

# ---------------------------------------------------------------------------
# Products
# ---------------------------------------------------------------------------
products = sqlite_store.PersistentDict(_conn, _lock, "products")
if not products:
    for i in range(1, 17):
        pid = f"P{i:03d}"
        stem = PRODUCT_NAME_STEMS[(i - 1) % len(PRODUCT_NAME_STEMS)]
        products[pid] = {
            "Id": pid,
            "Name": f"{stem} {chr(65 + i % 26)}-{100 + i}",
            "Category": PRODUCT_CATEGORIES[(i - 1) % len(PRODUCT_CATEGORIES)],
            "UnitPrice": random.choice([1500, 3200, 8000, 15000, 25000, 48000, 120000, 250000]),
            "Stock": random.randint(0, 300),
            "SafetyStock": random.randint(10, 50),
        }
product_ids = list(products.keys())

# ---------------------------------------------------------------------------
# Suppliers
# ---------------------------------------------------------------------------
suppliers = sqlite_store.PersistentDict(_conn, _lock, "suppliers")
if not suppliers:
    for i in range(1, 9):
        sid = f"S{i:03d}"
        suppliers[sid] = {
            "Id": sid,
            "Name": COMPANY_NAMES[(i + 5) % len(COMPANY_NAMES)] + "部品",
            "Category": PRODUCT_CATEGORIES[(i - 1) % len(PRODUCT_CATEGORIES)],
            "Tel": _tel(),
            "Address": f"大阪府大阪市北区梅田{random.randint(1,3)}-{random.randint(1,20)}",
            "ContactPerson": random.choice(PERSON_NAMES),
            "CreditAmount": random.choice([1000000, 3000000, 5000000, 10000000]),
            "PaymentTerms": random.choice(["月末締め翌月末払い", "月末締め翌々月10日払い", "納品都度払い"]),
            "Notes": "",
            "CreatedAt": _rand_date(-365, 0),
        }
supplier_ids = list(suppliers.keys())

# ---------------------------------------------------------------------------
# Employees
# ---------------------------------------------------------------------------
employees = sqlite_store.PersistentDict(_conn, _lock, "employees")
if not employees:
    for i in range(1, 14):
        eid = f"E{i:03d}"
        name = PERSON_NAMES[(i - 1) % len(PERSON_NAMES)]
        employees[eid] = {
            "Id": eid,
            "Name": name,
            "Department": random.choice(DEPARTMENTS),
            "Position": random.choice(POSITIONS),
            "Email": f"emp{i:03d}@legacy-erp.example.co.jp",
            "Tel": _tel(),
            "HireDate": _rand_date(-3650, -365),
            "CreatedAt": _rand_date(-365, 0),
        }

# ---------------------------------------------------------------------------
# 共通: 明細行生成ヘルパー
# ---------------------------------------------------------------------------
def _gen_items(prefix_id, n_min=1, n_max=4):
    items = []
    for _ in range(random.randint(n_min, n_max)):
        pid = random.choice(product_ids)
        p = products[pid]
        qty = random.randint(1, 20)
        items.append({
            "ProductId": pid,
            "ProductName": p["Name"],
            "Quantity": qty,
            "UnitPrice": p["UnitPrice"],
            "Amount": qty * p["UnitPrice"],
        })
    return items


# ---------------------------------------------------------------------------
# Orders + OrderItems
# ---------------------------------------------------------------------------
orders = sqlite_store.PersistentDict(_conn, _lock, "orders")
order_items = sqlite_store.PersistentDict(_conn, _lock, "order_items")
customer_ids = list(customers.keys())
if not orders:
    for i in range(1, 43):
        oid = f"ORD{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        items = _gen_items(oid)
        total = sum(it["Amount"] for it in items)
        order_date = _rand_date(-180, 0)
        orders[oid] = {
            "Id": oid,
            "CustomerId": cust["Id"],
            "CustomerName": cust["Name"],
            "OrderDate": order_date,
            "DeliveryDate": _rand_date(-30, 60),
            "TotalAmount": total,
            "Status": random.choice(ORDER_STATUSES),
            "Notes": "",
            "CreatedAt": order_date,
        }
        order_items[oid] = items

# ---------------------------------------------------------------------------
# Estimates + EstimateItems
# ---------------------------------------------------------------------------
estimates = sqlite_store.PersistentDict(_conn, _lock, "estimates")
estimate_items = sqlite_store.PersistentDict(_conn, _lock, "estimate_items")
if not estimates:
    for i in range(1, 18):
        eid = f"EST{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        items = _gen_items(eid)
        total = sum(it["Amount"] for it in items)
        est_date = _rand_date(-120, 0)
        estimates[eid] = {
            "Id": eid,
            "CustomerId": cust["Id"],
            "CustomerName": cust["Name"],
            "EstimateDate": est_date,
            "ValidUntil": _rand_date(-60, 30),
            "TotalAmount": total,
            "Status": random.choice(ESTIMATE_STATUSES),
            "Notes": "",
            "CreatedAt": est_date,
        }
        estimate_items[eid] = items

# ---------------------------------------------------------------------------
# PurchaseOrders + PurchaseOrderItems
# ---------------------------------------------------------------------------
purchase_orders = sqlite_store.PersistentDict(_conn, _lock, "purchase_orders")
purchase_order_items = sqlite_store.PersistentDict(_conn, _lock, "purchase_order_items")
if not purchase_orders:
    for i in range(1, 17):
        pid = f"PO{1000 + i}"
        sup = suppliers[random.choice(supplier_ids)]
        items = _gen_items(pid)
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
# Invoices（関連受注ベース）
# ---------------------------------------------------------------------------
invoices = sqlite_store.PersistentDict(_conn, _lock, "invoices")
order_id_list = list(orders.keys())
if not invoices:
    for i in range(1, 19):
        iid = f"INV{1000 + i}"
        order = orders[random.choice(order_id_list)]
        inv_date = _rand_date(-90, 0)
        invoices[iid] = {
            "Id": iid,
            "CustomerId": order["CustomerId"],
            "CustomerName": order["CustomerName"],
            "InvoiceDate": inv_date,
            "DueDate": _rand_date(-30, 30),
            "TotalAmount": order["TotalAmount"],
            "Status": random.choice(INVOICE_STATUSES),
            "OrderId": order["Id"],
            "Notes": "",
            "CreatedAt": inv_date,
        }

# ---------------------------------------------------------------------------
# Properties（物件）
# ---------------------------------------------------------------------------
properties = sqlite_store.PersistentDict(_conn, _lock, "properties")
PROPERTY_NAME_STEMS = ["レジデンス丸の内", "パークハイツ梅田", "サンシャイン品川", "グリーンヒルズ横浜",
                        "セントラルタワー名古屋", "ベイサイド福岡", "ヒルサイド渋谷", "リバーサイド京都"]
if not properties:
    for i in range(1, 9):
        pid = f"PR{i:03d}"
        name = PROPERTY_NAME_STEMS[(i - 1) % len(PROPERTY_NAME_STEMS)]
        properties[pid] = {
            "Id": pid,
            "Name": name,
            "NameKana": "レジデンス",
            "Address": f"東京都港区南青山{random.randint(1,5)}-{random.randint(1,20)}-{random.randint(1,10)}",
            "Access": "東京メトロ表参道駅 徒歩8分",
            "LandArea": round(random.uniform(80, 500), 2),
            "BuildingArea": round(random.uniform(60, 400), 2),
            "Structure": random.choice(["RC造", "SRC造", "鉄骨造", "木造"]),
            "Floors": random.randint(1, 20),
            "BuiltDate": _rand_date(-3650, -365),
            "LandRight": random.choice(["所有権", "定期借地権"]),
            "TransactionType": random.choice(["売買", "仲介", "代理"]),
            "Price": random.choice([28000000, 45000000, 68000000, 98000000, 150000000]),
            "MonthlyRent": random.choice([80000, 120000, 180000, 250000]),
            "OccupancyRate": round(random.uniform(70, 100), 2),
            "ParkingSpaces": random.randint(0, 20),
            "Facilities": "オートロック / 宅配ボックス / エレベーター",
            "CreatedAt": _rand_date(-365, 0),
        }

# ---------------------------------------------------------------------------
# InventoryTransaction（在庫トランザクション）
# ---------------------------------------------------------------------------
inventory_transactions = sqlite_store.PersistentList(_conn, _lock, "inventory_transactions")
TX_TYPES = ["入庫", "出庫", "棚卸調整"]
if not inventory_transactions:
    for i in range(1, 47):
        pid = random.choice(product_ids)
        p = products[pid]
        tx_type = random.choice(TX_TYPES)
        inventory_transactions.append({
            "Id": f"IT{i:05d}",
            "ProductId": pid,
            "ProductName": p["Name"],
            "Type": tx_type,
            "Quantity": random.randint(1, 50) * (1 if tx_type != "出庫" else -1),
            "Date": _rand_date(-180, 0),
            "Notes": "",
        })

# ---------------------------------------------------------------------------
# GoodsReceipt（入荷）
# ---------------------------------------------------------------------------
goods_receipts = sqlite_store.PersistentDict(_conn, _lock, "goods_receipts")
if not goods_receipts:
    for i in range(1, 16):
        gid = f"GR{1000 + i}"
        sup = suppliers[random.choice(supplier_ids)]
        pid = random.choice(product_ids)
        p = products[pid]
        goods_receipts[gid] = {
            "Id": gid,
            "SupplierId": sup["Id"],
            "SupplierName": sup["Name"],
            "ProductId": pid,
            "ProductName": p["Name"],
            "Quantity": random.randint(5, 100),
            "ReceiptDate": _rand_date(-90, 0),
        }

# ---------------------------------------------------------------------------
# ArAp（売掛買掛） — 顧客/仕入先ごとの残高を集計
# ---------------------------------------------------------------------------
def build_arap():
    rows = []
    for c in customers.values():
        unpaid = sum(inv["TotalAmount"] for inv in invoices.values()
                     if inv["CustomerId"] == c["Id"] and inv["Status"] != "入金済")
        if unpaid > 0:
            rows.append({"Type": "売掛金", "PartnerName": c["Name"], "Balance": unpaid})
    for s in suppliers.values():
        unpaid = sum(po["TotalAmount"] for po in purchase_orders.values()
                     if po["SupplierId"] == s["Id"] and po["Status"] != "入荷済")
        if unpaid > 0:
            rows.append({"Type": "買掛金", "PartnerName": s["Name"], "Balance": unpaid})
    return rows


# ---------------------------------------------------------------------------
# Profit（利益） — 商品別 売上/原価/粗利/粗利率
# ---------------------------------------------------------------------------
def build_profit():
    rows = []
    for pid, p in products.items():
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
    "GoodsReceipt": len(goods_receipts),
}
_ID_FORMATS = {
    "Customer": "C{:04d}", "Order": "ORD{:04d}", "Estimate": "EST{:04d}",
    "PurchaseOrder": "PO{:04d}", "Invoice": "INV{:04d}", "Supplier": "S{:03d}",
    "Employee": "E{:03d}", "Property": "PR{:03d}", "GoodsReceipt": "GR{:04d}",
}


def next_id(entity: str) -> str:
    _counters[entity] += 1
    n = _counters[entity]
    fmt = _ID_FORMATS[entity]
    # ORD/EST/PO/INV/GRは元データが1000番台始まりなので揃える
    if entity in ("Order", "Estimate", "PurchaseOrder", "Invoice", "GoodsReceipt"):
        return fmt.format(1000 + n)
    return fmt.format(n)
