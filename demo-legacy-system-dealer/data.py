"""
デモ・レガシーシステム（自動車ディーラー版）インメモリ「DB」
====================================================
demo-legacy-system（製造業向けERP）と同じ設計方針（7.1章 方式B: 独立インメモリ
ストア）を、日本の中古車・新車ディーラーの基幹業務ドメインに置き換えたもの。
エンティティ構造・ヘルパー関数のシェイプは意図的に元ERPデモと揃えてあり、
main.py 側の汎用レンダリング処理（render_list/render_entry/render_detail）を
無改造で再利用できるようにしている。

業務ドメイン対応表（元ERP → 自動車ディーラー）:
  Product（商品/在庫）   → Vehicle（車両在庫）: 型式ごとの複数在庫という構造は維持しつつ
                            車台番号(VIN)・年式・走行距離・色などの車両属性を追加
  Order（受注）          → 受注/契約: 車両＋付属品（オプション用品）の明細行
  PurchaseOrder（発注）  → 仕入: オークション/下取りによる車両仕入
  GoodsReceipt（入荷）   → 入庫: 仕入れた車両の店舗入庫登録
  Property（物件）       → 廃止（自動車ディーラーには該当しないため削除）
  （新設）ServiceOrder   → 整備/車検: 自動車ディーラー特有の業務（元ERPには存在しない
                            エンティティを新規追加できることを示すデモも兼ねる）
"""
import os
import random
from datetime import datetime, timedelta

import sqlite_store

random.seed(42)

# ---------------------------------------------------------------------------
# 永続化(SQLite)
# ---------------------------------------------------------------------------
# demo-legacy-system-dealer専用のDBファイル。demo-legacy-system(ERP版、別プロセス/
# 別ディレクトリ)とはファイルパスも接続オブジェクトも完全に分離しており、
# 互いのプロセスが起動していても一切干渉しない。
_DB_PATH = os.getenv("AISB_DEALER_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "dealer.db"))
_conn, _lock = sqlite_store.open_db(_DB_PATH)

# ---------------------------------------------------------------------------
# マスタ用の名称プール
# ---------------------------------------------------------------------------
PERSON_NAMES = [
    "山田太郎", "佐藤花子", "鈴木一郎", "高橋直美", "田中健太", "伊藤あゆみ",
    "渡辺修", "中村ゆり", "小林大輔", "加藤麻衣", "吉田誠", "山本裕子",
    "松本剛", "井上恵子", "木村隆", "林由美", "斎藤浩二", "清水香織",
]
COMPANY_CUSTOMER_NAMES = [
    "山田運送", "佐藤商事", "鈴木興業", "高橋物流", "田中リース", "共同タクシー",
]
DEPARTMENTS = ["営業部", "整備部", "買取査定部", "事務部", "管理部"]
POSITIONS = ["店長", "主任", "係長", "一般スタッフ", "整備士"]

MAKER_MODELS = [
    ("トヨタ", "カローラ", "セダン"), ("トヨタ", "ヤリス", "コンパクト"),
    ("トヨタ", "アルファード", "ミニバン"), ("トヨタ", "ハリアー", "SUV"),
    ("トヨタ", "プリウス", "セダン"), ("ホンダ", "フィット", "コンパクト"),
    ("ホンダ", "ヴェゼル", "SUV"), ("ホンダ", "フリード", "ミニバン"),
    ("日産", "ノート", "コンパクト"), ("日産", "セレナ", "ミニバン"),
    ("日産", "エクストレイル", "SUV"), ("マツダ", "CX-5", "SUV"),
    ("マツダ", "MAZDA2", "コンパクト"), ("スバル", "フォレスター", "SUV"),
    ("スズキ", "ハスラー", "軽自動車"), ("ダイハツ", "タント", "軽自動車"),
]
GRADES = ["G", "X", "S", "ハイブリッドG", "Lパッケージ", "ベースグレード"]
COLORS = ["ホワイトパール", "ブラック", "シルバー", "レッド", "ブルー", "ダークグレーM"]
TRANSMISSIONS = ["AT", "CVT"]
FUEL_TYPES = ["ガソリン", "ハイブリッド"]
CONDITION_TYPES = ["新車", "中古車(自社買取)", "中古車(オークション仕入)"]
SERVICE_TYPES = ["車検", "法定12ヶ月点検", "一般整備", "板金・塗装", "オイル交換"]
ORDER_STATUSES = ["商談中", "契約済", "納車準備中", "納車完了", "キャンセル"]
ESTIMATE_STATUSES = ["作成中", "提示済", "成約", "失注"]
INVOICE_STATUSES = ["未払い", "入金済", "延滞"]
PO_STATUSES = ["仕入交渉中", "入庫済", "キャンセル"]
SERVICE_STATUSES = ["予約", "作業中", "完了"]


def _rand_date(min_days=-180, max_days=30):
    """base(今日)から見て [min_days, max_days] 日オフセットの日付を返す（負=過去/正=未来）。"""
    base = datetime(2026, 7, 25)
    delta = random.randint(min_days, max_days)
    return (base + timedelta(days=delta)).strftime("%Y-%m-%d")


def _postal():
    return f"{random.randint(100,999)}-{random.randint(1000,9999)}"


def _tel():
    return f"0{random.randint(1,9)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"


def _vin():
    return f"{random.choice('ABCDEFGHJK')}{random.randint(10,99)}-{random.randint(1000000,9999999)}"


# ---------------------------------------------------------------------------
# Customers（顧客）
# ---------------------------------------------------------------------------
customers = sqlite_store.PersistentDict(_conn, _lock, "customers")
if not customers:
    for i in range(1, 17):
        cid = f"C{i:04d}"
        is_corp = i % 5 == 0
        limit = random.choice([500000, 1000000, 2000000, 3000000, 5000000])
        used = random.randint(0, limit)
        customers[cid] = {
            "Id": cid,
            "Name": COMPANY_CUSTOMER_NAMES[(i // 5 - 1) % len(COMPANY_CUSTOMER_NAMES)] if is_corp
                    else PERSON_NAMES[(i - 1) % len(PERSON_NAMES)],
            "NameKana": "ヤマダタロウ" if not is_corp else "カブシキガイシャ",
            "CustomerType": "法人" if is_corp else "個人",
            "PostalCode": _postal(),
            "Address": f"東京都世田谷区北沢{random.randint(1,5)}-{random.randint(1,20)}-{random.randint(1,10)}",
            "Tel": _tel(),
            "Email": f"customer{i:03d}@example.co.jp",
            "DriverLicenseNo": f"{random.randint(100000,999999)}{random.randint(100000,999999)}" if not is_corp else "",
            "CreditLimit": limit,
            "CreditUsed": used,
            "Notes": "",
            "CreatedAt": _rand_date(-365, 0),
        }
customer_ids = list(customers.keys())

# ---------------------------------------------------------------------------
# Vehicles（車両在庫） — 元ERPの Product に相当
# ---------------------------------------------------------------------------
vehicles = sqlite_store.PersistentDict(_conn, _lock, "vehicles")
if not vehicles:
    for i in range(1, 17):
        pid = f"V{i:03d}"
        maker, model, body_type = MAKER_MODELS[(i - 1) % len(MAKER_MODELS)]
        grade = GRADES[(i - 1) % len(GRADES)]
        condition = CONDITION_TYPES[(i - 1) % len(CONDITION_TYPES)]
        is_new = condition == "新車"
        vehicles[pid] = {
            "Id": pid,
            "Name": f"{maker} {model} {grade}",
            "Maker": maker,
            "Model": model,
            "Category": body_type,
            "Grade": grade,
            "Year": random.randint(2019, 2026) if not is_new else 2026,
            "Mileage": 0 if is_new else random.randint(3000, 90000),
            "Color": random.choice(COLORS),
            "Transmission": random.choice(TRANSMISSIONS),
            "FuelType": random.choice(FUEL_TYPES),
            "ConditionType": condition,
            "VIN": _vin(),
            "UnitPrice": random.choice([980000, 1480000, 1980000, 2480000, 2980000, 3980000]),
            "Stock": random.randint(0, 6),
            "SafetyStock": random.randint(1, 3),
        }
vehicle_ids = list(vehicles.keys())

# ---------------------------------------------------------------------------
# Suppliers（仕入先） — オークション会場・下取り仲介・メーカー卸
# ---------------------------------------------------------------------------
suppliers = sqlite_store.PersistentDict(_conn, _lock, "suppliers")
SUPPLIER_NAMES = [
    "USS東京オークション", "JU中央オークション", "CAA中部オークション",
    "全国下取りネットワーク", "トヨタ卸販売", "日産ディーラー卸",
    "ホンダカーズ卸部門", "地域買取センター",
]
SUPPLIER_CATEGORIES = ["オークション会場", "下取り仲介", "メーカー卸", "個人買取"]
if not suppliers:
    for i in range(1, 9):
        sid = f"S{i:03d}"
        suppliers[sid] = {
            "Id": sid,
            "Name": SUPPLIER_NAMES[(i - 1) % len(SUPPLIER_NAMES)],
            "Category": SUPPLIER_CATEGORIES[(i - 1) % len(SUPPLIER_CATEGORIES)],
            "Tel": _tel(),
            "Address": f"愛知県名古屋市中村区{random.randint(1,3)}-{random.randint(1,20)}",
            "ContactPerson": random.choice(PERSON_NAMES),
            "CreditAmount": random.choice([3000000, 5000000, 10000000, 20000000]),
            "PaymentTerms": random.choice(["月末締め翌月末払い", "落札都度払い", "納車都度払い"]),
            "Notes": "",
            "CreatedAt": _rand_date(-365, 0),
        }
supplier_ids = list(suppliers.keys())

# ---------------------------------------------------------------------------
# Employees（従業員）
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
            "Email": f"staff{i:03d}@auto-dealer.example.co.jp",
            "Tel": _tel(),
            "HireDate": _rand_date(-3650, -365),
            "CreatedAt": _rand_date(-365, 0),
        }
employee_ids = list(employees.keys())
mechanic_ids = [e for e in employee_ids if employees[e]["Department"] == "整備部"] or employee_ids

# ---------------------------------------------------------------------------
# 共通: 明細行生成ヘルパー（受注/見積/仕入の車両明細）
# ---------------------------------------------------------------------------
def _gen_items(n_min=1, n_max=2):
    items = []
    for _ in range(random.randint(n_min, n_max)):
        pid = random.choice(vehicle_ids)
        p = vehicles[pid]
        qty = 1
        items.append({
            "ProductId": pid,
            "ProductName": p["Name"],
            "Quantity": qty,
            "UnitPrice": p["UnitPrice"],
            "Amount": qty * p["UnitPrice"],
        })
    return items


# ---------------------------------------------------------------------------
# Orders + OrderItems（受注/契約）
# ---------------------------------------------------------------------------
orders = sqlite_store.PersistentDict(_conn, _lock, "orders")
order_items = sqlite_store.PersistentDict(_conn, _lock, "order_items")
if not orders:
    for i in range(1, 43):
        oid = f"ORD{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        items = _gen_items()
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
# Estimates + EstimateItems（見積）
# ---------------------------------------------------------------------------
estimates = sqlite_store.PersistentDict(_conn, _lock, "estimates")
estimate_items = sqlite_store.PersistentDict(_conn, _lock, "estimate_items")
if not estimates:
    for i in range(1, 18):
        eid = f"EST{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        items = _gen_items()
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
# PurchaseOrders + PurchaseOrderItems（仕入）
# ---------------------------------------------------------------------------
purchase_orders = sqlite_store.PersistentDict(_conn, _lock, "purchase_orders")
purchase_order_items = sqlite_store.PersistentDict(_conn, _lock, "purchase_order_items")
if not purchase_orders:
    for i in range(1, 17):
        pid = f"PO{1000 + i}"
        sup = suppliers[random.choice(supplier_ids)]
        items = _gen_items()
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
# Invoices（請求、関連受注ベース）
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
# InventoryTransaction（車両入出庫履歴）
# ---------------------------------------------------------------------------
inventory_transactions = sqlite_store.PersistentList(_conn, _lock, "inventory_transactions")
TX_TYPES = ["入庫", "出庫", "棚卸調整"]
if not inventory_transactions:
    for i in range(1, 47):
        pid = random.choice(vehicle_ids)
        p = vehicles[pid]
        tx_type = random.choice(TX_TYPES)
        inventory_transactions.append({
            "Id": f"IT{i:05d}",
            "ProductId": pid,
            "ProductName": p["Name"],
            "Type": tx_type,
            "Quantity": random.randint(1, 3) * (1 if tx_type != "出庫" else -1),
            "Date": _rand_date(-180, 0),
            "Notes": "",
        })

# ---------------------------------------------------------------------------
# GoodsReceipt（入庫） — 仕入れた車両の店舗入庫登録
# ---------------------------------------------------------------------------
goods_receipts = sqlite_store.PersistentDict(_conn, _lock, "goods_receipts")
if not goods_receipts:
    for i in range(1, 16):
        gid = f"GR{1000 + i}"
        sup = suppliers[random.choice(supplier_ids)]
        pid = random.choice(vehicle_ids)
        p = vehicles[pid]
        goods_receipts[gid] = {
            "Id": gid,
            "SupplierId": sup["Id"],
            "SupplierName": sup["Name"],
            "ProductId": pid,
            "ProductName": p["Name"],
            "Quantity": random.randint(1, 3),
            "ReceiptDate": _rand_date(-90, 0),
        }

# ---------------------------------------------------------------------------
# ServiceOrder（整備/車検） — 自動車ディーラー特有の新設エンティティ
# ---------------------------------------------------------------------------
service_orders = sqlite_store.PersistentDict(_conn, _lock, "service_orders")
if not service_orders:
    for i in range(1, 21):
        svid = f"SVC{1000 + i}"
        cust = customers[random.choice(customer_ids)]
        pid = random.choice(vehicle_ids)
        p = vehicles[pid]
        mech = employees[random.choice(mechanic_ids)]
        svc_date = _rand_date(-120, 30)
        service_orders[svid] = {
            "Id": svid,
            "CustomerId": cust["Id"],
            "CustomerName": cust["Name"],
            "VehicleId": pid,
            "VehicleName": p["Name"],
            "ServiceType": random.choice(SERVICE_TYPES),
            "ServiceDate": svc_date,
            "Cost": random.choice([8000, 15000, 35000, 60000, 120000]),
            "Mechanic": mech["Name"],
            "Status": random.choice(SERVICE_STATUSES),
            "Notes": "",
            "CreatedAt": svc_date,
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
                     if po["SupplierId"] == s["Id"] and po["Status"] != "入庫済")
        if unpaid > 0:
            rows.append({"Type": "買掛金", "PartnerName": s["Name"], "Balance": unpaid})
    return rows


# ---------------------------------------------------------------------------
# Profit（利益） — 車両別 売上/原価/粗利/粗利率
# ---------------------------------------------------------------------------
def build_profit():
    rows = []
    for pid, p in vehicles.items():
        sales = sum(it["Amount"] for items in order_items.values() for it in items if it["ProductId"] == pid)
        if sales == 0:
            continue
        cost = round(sales * random.uniform(0.75, 0.9))
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
    "Supplier": len(suppliers), "Employee": len(employees),
    "GoodsReceipt": len(goods_receipts), "ServiceOrder": len(service_orders),
}
_ID_FORMATS = {
    "Customer": "C{:04d}", "Order": "ORD{:04d}", "Estimate": "EST{:04d}",
    "PurchaseOrder": "PO{:04d}", "Invoice": "INV{:04d}", "Supplier": "S{:03d}",
    "Employee": "E{:03d}", "GoodsReceipt": "GR{:04d}", "ServiceOrder": "SVC{:04d}",
}


def next_id(entity: str) -> str:
    _counters[entity] += 1
    n = _counters[entity]
    fmt = _ID_FORMATS[entity]
    if entity in ("Order", "Estimate", "PurchaseOrder", "Invoice", "GoodsReceipt", "ServiceOrder"):
        return fmt.format(1000 + n)
    return fmt.format(n)
