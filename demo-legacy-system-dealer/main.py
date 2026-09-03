"""
デモ・レガシーシステム（自動車ディーラー版, localhost:5020）
======================================
AI機能ゼロの模擬WebForms風・自動車ディーラー基幹システム（DMS: Dealer Management
System）。全10業務エンティティ（Customer/Vehicle(Stock)/Supplier/Employee/
Estimate/Order(受注契約)/Invoice/PurchaseOrder(仕入)/InventoryTransaction/
GoodsReceipt(入庫)/ArAp/Profit/ServiceOrder(整備・車検)）に対応するサーバーサイド
HTMLレンダリング（Jinja2）画面群。

demo-legacy-system（製造業ERP版）と全く同じ設計を、自動車ディーラーの業務ドメインに
適用したもの（3. プロジェクト概要参照）:「既存のレガシーシステムを一切変更せずに
AI機能を付与する」という AI-Sync Bridge のコンセプトが、業種を問わず同じ仕組み
（aisb_embed のミドルウェア注入 + 読み取り専用JSON API）で成立することを示すデモ。

SPAではなく伝統的なページ遷移型。AI-Sync Bridge（aisb_embed）がこのDOM上に
サイドバーを注入する「未改変ターゲット」。ai-api-server とはプロセスが完全に
独立しており、ダミーデータも独立したインメモリストア（data.py）を持つ。
"""
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import data as db
import aisb_embed  # AIサイドバー埋め込み(任意・トグル可能)。レガシー側コードへの依存はこの2行のみ。

BASE_DIR = Path(__file__).parent

app = FastAPI(title="Auto Dealer DMS (Demo)")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# サブパス経由公開(例: https://host/dealer/... 経由でCaddyがstrip_prefixする構成)対応。
# Caddy側がX-Forwarded-Prefixを付与した場合のみ、テンプレート内の絶対パスリンクに
# プレフィックスを補う。ヘッダーが無ければ従来通り""(=完全無改変の挙動)。
templates.env.globals["base_path"] = lambda request: request.headers.get("x-forwarded-prefix", "")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def redirect_to(request: Request, path: str, status_code: int = 303) -> RedirectResponse:
    """POST後リダイレクト用。X-Forwarded-Prefix配下でも遷移先を正しく維持する。
    GET側テンプレートの base_path(request) と同じロジック（ヘッダー未設定時は""=無改変）。"""
    prefix = request.headers.get("x-forwarded-prefix", "")
    return RedirectResponse(f"{prefix}{path}", status_code=status_code)


aisb_embed.mount(app)


# ---------------------------------------------------------------------------
# 共通ヘルパー（demo-legacy-system と同一実装）
# ---------------------------------------------------------------------------
def field(name, label, type_="text", options=None, required=False):
    return {"name": name, "label": label, "type": type_, "options": options, "required": required}


def form_values(form, fields):
    values = {}
    for f in fields:
        raw = form.get(f["name"], "")
        if f["type"] == "number":
            try:
                values[f["name"]] = int(float(raw)) if raw != "" else 0
            except ValueError:
                values[f["name"]] = 0
        else:
            values[f["name"]] = raw
    return values


PAGE_SIZE = 15


def paginate(request: Request, rows: list):
    try:
        page = max(1, int(request.query_params.get("page", 1)))
    except ValueError:
        page = 1
    total = len(rows)
    total_pages = max(1, (total + PAGE_SIZE - 1) // PAGE_SIZE)
    page = min(page, total_pages)
    start = (page - 1) * PAGE_SIZE
    page_rows = rows[start:start + PAGE_SIZE]
    return page_rows, {"page": page, "total_pages": total_pages, "total": total}


def render_list(request, *, title, heading, entity_path, columns, rows, id_field="Id",
                 show_entry=True, show_detail=True, show_search=False, new_label=None,
                 money_fields=None, rate_fields=None, paged=True):
    page_info = None
    if paged:
        rows, page_info = paginate(request, rows)
    return templates.TemplateResponse(request, "list.html", {
        "title": title, "heading": heading, "entity_path": entity_path,
        "columns": columns, "rows": rows, "id_field": id_field,
        "show_entry": show_entry, "show_detail": show_detail, "show_search": show_search,
        "new_label": new_label, "money_fields": money_fields or set(), "rate_fields": rate_fields or set(),
        "page_info": page_info,
    })


def render_entry(request, *, title, heading, entity_path, fields, values, is_edit, record_id=None):
    return templates.TemplateResponse(request, "entry.html", {
        "title": title, "heading": heading, "entity_path": entity_path,
        "fields": fields, "values": values, "is_edit": is_edit, "record_id": record_id,
    })


def render_detail(request, *, title, heading, entity_path, fields, values, record_id,
                   show_entry=True, items=None, money_fields=None):
    return templates.TemplateResponse(request, "detail.html", {
        "title": title, "heading": heading, "entity_path": entity_path,
        "fields": fields, "values": values, "record_id": record_id,
        "show_entry": show_entry, "items": items, "money_fields": money_fields or set(),
    })


# ---------------------------------------------------------------------------
# フィールド定義（各エンティティのフォーム/一覧メタデータ）
# ---------------------------------------------------------------------------
CUSTOMER_FIELDS = [
    field("Name", "氏名/会社名", required=True),
    field("NameKana", "カナ"),
    field("CustomerType", "顧客区分", "select", ["個人", "法人"]),
    field("PostalCode", "郵便番号"),
    field("Address", "住所"),
    field("Tel", "TEL"),
    field("Email", "メール"),
    field("DriverLicenseNo", "運転免許証番号"),
    field("CreditLimit", "与信/ローン限度額", "number"),
    field("Notes", "備考", "textarea"),
]
CUSTOMER_LIST_COLUMNS = [
    ("Id", "ID"), ("Name", "氏名/会社名"), ("Tel", "TEL"), ("Address", "住所"),
    ("CreditLimit", "与信限度額"), ("CreditRate", "与信使用率"),
]

SUPPLIER_FIELDS = [
    field("Name", "仕入先名", required=True),
    field("Category", "仕入区分"),
    field("Tel", "TEL"),
    field("Address", "住所"),
    field("ContactPerson", "担当者"),
    field("CreditAmount", "与信枠", "number"),
    field("PaymentTerms", "支払条件"),
    field("Notes", "備考", "textarea"),
]
SUPPLIER_LIST_COLUMNS = [
    ("Id", "ID"), ("Name", "仕入先名"), ("Category", "仕入区分"), ("Tel", "TEL"),
    ("ContactPerson", "担当者"), ("CreditAmount", "与信枠"),
]

EMPLOYEE_FIELDS = [
    field("Name", "氏名", required=True),
    field("Department", "部署", "select", db.DEPARTMENTS),
    field("Position", "役職", "select", db.POSITIONS),
    field("Email", "メール"),
    field("Tel", "TEL"),
    field("HireDate", "入社日", "date"),
]
EMPLOYEE_LIST_COLUMNS = [
    ("Id", "ID"), ("Name", "氏名"), ("Department", "部署"), ("Position", "役職"),
    ("Email", "メール"), ("Tel", "TEL"),
]

INVOICE_FIELDS = [
    field("CustomerId", "顧客", "select", required=True),  # options injected per-request
    field("InvoiceDate", "請求日", "date"),
    field("DueDate", "支払期日", "date"),
    field("TotalAmount", "金額", "number", required=True),
    field("OrderId", "関連受注", "select"),
    field("Notes", "備考", "textarea"),
]
INVOICE_LIST_COLUMNS = [
    ("Id", "請求番号"), ("CustomerName", "顧客名"), ("InvoiceDate", "請求日"),
    ("DueDate", "支払期日"), ("TotalAmount", "金額"), ("Status", "ステータス"),
]

GOODSRECEIPT_FIELDS = [
    field("SupplierId", "仕入先", "select", required=True),
    field("ProductId", "車両", "select", required=True),
    field("Quantity", "数量", "number", required=True),
    field("ReceiptDate", "入庫日", "date"),
]
GOODSRECEIPT_LIST_COLUMNS = [
    ("Id", "ID"), ("SupplierName", "仕入先"), ("ProductName", "車両"),
    ("Quantity", "数量"), ("ReceiptDate", "入庫日"),
]

SERVICEORDER_FIELDS = [
    field("CustomerId", "顧客", "select", required=True),
    field("VehicleId", "車両", "select", required=True),
    field("ServiceType", "整備種別", "select", db.SERVICE_TYPES, required=True),
    field("ServiceDate", "整備日", "date"),
    field("Cost", "費用", "number", required=True),
    field("Mechanic", "担当整備士"),
    field("Status", "ステータス", "select", db.SERVICE_STATUSES),
    field("Notes", "備考", "textarea"),
]
SERVICEORDER_LIST_COLUMNS = [
    ("Id", "整備番号"), ("CustomerName", "顧客名"), ("VehicleName", "車両"),
    ("ServiceType", "整備種別"), ("ServiceDate", "整備日"), ("Cost", "費用"), ("Status", "ステータス"),
]

ORDER_LIST_COLUMNS = [
    ("Id", "受注ID"), ("CustomerName", "顧客名"), ("OrderDate", "受注日"),
    ("DeliveryDate", "納車予定日"), ("TotalAmount", "合計金額"), ("Status", "ステータス"), ("Notes", "備考"),
]
ESTIMATE_LIST_COLUMNS = [
    ("Id", "見積番号"), ("CustomerName", "顧客名"), ("EstimateDate", "見積日"),
    ("ValidUntil", "有効期限"), ("TotalAmount", "合計金額"), ("Status", "ステータス"),
]
PO_LIST_COLUMNS = [
    ("Id", "仕入番号"), ("SupplierName", "仕入先"), ("OrderDate", "仕入日"),
    ("DeliveryDate", "入庫予定日"), ("TotalAmount", "合計金額"), ("Status", "ステータス"),
]
INVTX_LIST_COLUMNS = [
    ("ProductName", "車両"), ("Type", "種別"), ("Quantity", "数量"), ("Date", "日付"), ("Notes", "備考"),
]


def customer_options():
    return [(c["Id"], c["Name"]) for c in db.customers.values()]


def supplier_options():
    return [(s["Id"], s["Name"]) for s in db.suppliers.values()]


def vehicle_options():
    return [(v["Id"], v["Name"]) for v in db.vehicles.values()]


def vehicle_list():
    return list(db.vehicles.values())


# ---------------------------------------------------------------------------
# JSON API（AI-Sync Bridge 連携用・読み取り専用。demo-legacy-systemと同一設計）
# ---------------------------------------------------------------------------
ENTITY_LABELS = {
    "Customer": "顧客", "Order": "受注/契約", "Product": "車両在庫", "Supplier": "仕入先",
    "Employee": "従業員", "Estimate": "見積", "Invoice": "請求", "PurchaseOrder": "仕入",
    "InventoryTransaction": "車両入出庫", "GoodsReceipt": "入庫", "ArAp": "売掛買掛",
    "Profit": "利益", "ServiceOrder": "整備/車検",
}

_ENTITY_ROWS = {
    "Customer": lambda: list(db.customers.values()),
    "Order": lambda: list(db.orders.values()),
    "Product": lambda: list(db.vehicles.values()),
    "Supplier": lambda: list(db.suppliers.values()),
    "Employee": lambda: list(db.employees.values()),
    "Estimate": lambda: list(db.estimates.values()),
    "Invoice": lambda: list(db.invoices.values()),
    "PurchaseOrder": lambda: list(db.purchase_orders.values()),
    "InventoryTransaction": lambda: list(db.inventory_transactions),
    "GoodsReceipt": lambda: list(db.goods_receipts.values()),
    "ArAp": lambda: db.build_arap(),
    "Profit": lambda: db.build_profit(),
    "ServiceOrder": lambda: list(db.service_orders.values()),
}

_ENTITY_STORE = {
    "Customer": db.customers, "Order": db.orders, "Supplier": db.suppliers,
    "Employee": db.employees, "Estimate": db.estimates, "Invoice": db.invoices,
    "PurchaseOrder": db.purchase_orders, "ServiceOrder": db.service_orders,
}

_ENTITY_ITEMS = {
    "Order": db.order_items, "Estimate": db.estimate_items, "PurchaseOrder": db.purchase_order_items,
}


@app.get("/api/entities")
def api_entities():
    return [{"entity": k, "label": v, "hasDetail": k in _ENTITY_STORE} for k, v in ENTITY_LABELS.items()]


@app.get("/api/{entity}/list")
def api_entity_list(entity: str, q: str = "", limit: int = 100):
    if entity not in ENTITY_LABELS:
        raise HTTPException(404, f"unknown entity: {entity}")
    rows = _ENTITY_ROWS[entity]()
    if q:
        ql = q.lower()
        rows = [r for r in rows if any(ql in str(v).lower() for v in r.values())]
    return {"entity": entity, "label": ENTITY_LABELS[entity], "count": len(rows), "rows": rows[:limit]}


@app.get("/api/{entity}/detail/{rid}")
def api_entity_detail(entity: str, rid: str):
    store = _ENTITY_STORE.get(entity)
    if store is None:
        raise HTTPException(404, f"no detail endpoint for entity: {entity}")
    record = store.get(rid)
    if not record:
        raise HTTPException(404, "record not found")
    result = {"entity": entity, "label": ENTITY_LABELS[entity], "record": record}
    if entity in _ENTITY_ITEMS:
        result["items"] = _ENTITY_ITEMS[entity].get(rid, [])
    return result


# ---------------------------------------------------------------------------
# Home / Dashboard
# ---------------------------------------------------------------------------
@app.get("/")
def home(request: Request):
    summary = {
        "customers": len(db.customers),
        "orders": len(db.orders),
        "vehicles": len(db.vehicles),
        "sales_total": sum(o["TotalAmount"] for o in db.orders.values()),
    }
    return templates.TemplateResponse(request, "index.html", {"title": "メインメニュー", "summary": summary})


@app.get("/ai-panel")
def ai_panel_intro(request: Request):
    return templates.TemplateResponse(request, "ai_intro.html", {"title": "AIサイドパネルのご案内"})


# ---------------------------------------------------------------------------
# Customer（顧客管理）
# ---------------------------------------------------------------------------
@app.get("/Customer/List")
def customer_list(request: Request):
    rows = []
    for c in db.customers.values():
        row = dict(c)
        row["CreditRate"] = round((c["CreditUsed"] / c["CreditLimit"]) * 100, 1) if c["CreditLimit"] else 0
        rows.append(row)
    return render_list(request, title="顧客一覧", heading="顧客一覧", entity_path="Customer",
                        columns=CUSTOMER_LIST_COLUMNS, rows=rows, show_search=True,
                        new_label="顧客新規登録", money_fields={"CreditLimit"}, rate_fields={"CreditRate"})


@app.get("/Customer/Entry")
def customer_entry_new(request: Request):
    return render_entry(request, title="顧客新規登録", heading="顧客新規登録", entity_path="Customer",
                         fields=CUSTOMER_FIELDS, values={}, is_edit=False)


@app.get("/Customer/Entry/{cid}")
def customer_entry_edit(request: Request, cid: str):
    c = db.customers.get(cid)
    if not c:
        return redirect_to(request, "/Customer/List")
    return render_entry(request, title="顧客編集", heading="顧客編集", entity_path="Customer",
                         fields=CUSTOMER_FIELDS, values=c, is_edit=True, record_id=cid)


@app.post("/Customer/Entry")
async def customer_create(request: Request):
    form = await request.form()
    values = form_values(form, CUSTOMER_FIELDS)
    cid = db.next_id("Customer")
    values.update({"Id": cid, "CreditUsed": 0, "CreatedAt": db._rand_date(0, 0)})
    db.customers[cid] = values
    return redirect_to(request, "/Customer/List")


@app.post("/Customer/Entry/{cid}")
async def customer_update(request: Request, cid: str):
    form = await request.form()
    values = form_values(form, CUSTOMER_FIELDS)
    existing = db.customers.get(cid, {})
    existing.update(values)
    existing["Id"] = cid
    db.customers[cid] = existing
    return redirect_to(request, "/Customer/List")


@app.get("/Customer/Detail/{cid}")
def customer_detail(request: Request, cid: str):
    c = db.customers.get(cid)
    if not c:
        return redirect_to(request, "/Customer/List")
    return render_detail(request, title="顧客詳細", heading="顧客詳細", entity_path="Customer",
                          fields=CUSTOMER_FIELDS, values=c, record_id=cid, money_fields={"CreditLimit"})


@app.get("/Customer/Search")
def customer_search_form(request: Request):
    return templates.TemplateResponse(request, "customer_search.html",
                                       {"title": "顧客検索", "keyword": None, "results": None})


@app.post("/Customer/Search")
async def customer_search_submit(request: Request):
    form = await request.form()
    keyword = (form.get("keyword") or "").strip()
    results = list(db.customers.values())
    if keyword:
        results = [c for c in results if keyword in c["Name"] or keyword in (c["Tel"] or "")
                   or keyword in (c["Address"] or "")]
    return templates.TemplateResponse(request, "customer_search.html",
                                       {"title": "顧客検索", "keyword": keyword, "results": results})


# ---------------------------------------------------------------------------
# Order（受注/契約管理） — 明細行グリッド付き（最重要画面）
# ---------------------------------------------------------------------------
def parse_item_rows(form):
    product_ids = form.getlist("productId")
    quantities = form.getlist("quantity")
    items = []
    for pid, qty in zip(product_ids, quantities):
        if not pid:
            continue
        p = db.vehicles.get(pid)
        if not p:
            continue
        try:
            q = int(qty)
        except (TypeError, ValueError):
            q = 0
        items.append({
            "ProductId": pid, "ProductName": p["Name"], "Quantity": q,
            "UnitPrice": p["UnitPrice"], "Amount": q * p["UnitPrice"],
        })
    return items


@app.get("/Order/List")
def order_list(request: Request):
    return render_list(request, title="受注/契約一覧", heading="受注/契約一覧", entity_path="Order",
                        columns=ORDER_LIST_COLUMNS, rows=list(db.orders.values()), show_search=False,
                        new_label="受注新規登録", money_fields={"TotalAmount"})


@app.get("/Order/Entry")
def order_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "受注入力", "heading": "受注入力", "entity_path": "Order",
        "partner_label": "顧客", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "受注日", "date1_name": "orderDate", "date2_label": "納車予定日", "date2_name": "deliveryDate",
        "products": vehicle_list(), "items": [], "values": {}, "is_edit": False,
        "total_elem_id": "order-total",
    })


@app.get("/Order/Entry/{oid}")
def order_entry_edit(request: Request, oid: str):
    o = db.orders.get(oid)
    if not o:
        return redirect_to(request, "/Order/List")
    values = dict(o)
    values["customerId"] = o["CustomerId"]
    values["orderDate"] = o["OrderDate"]
    values["deliveryDate"] = o["DeliveryDate"]
    values["_total"] = o["TotalAmount"]
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "受注編集", "heading": "受注編集", "entity_path": "Order",
        "partner_label": "顧客", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "受注日", "date1_name": "orderDate", "date2_label": "納車予定日", "date2_name": "deliveryDate",
        "products": vehicle_list(), "items": db.order_items.get(oid, []), "values": values,
        "is_edit": True, "record_id": oid, "total_elem_id": "order-total",
    })


@app.post("/Order/Entry")
async def order_create(request: Request):
    form = await request.form()
    cust = db.customers.get(form.get("customerId"))
    items = parse_item_rows(form)
    total = sum(it["Amount"] for it in items)
    oid = db.next_id("Order")
    db.orders[oid] = {
        "Id": oid, "CustomerId": cust["Id"] if cust else "", "CustomerName": cust["Name"] if cust else "不明",
        "OrderDate": form.get("orderDate", ""), "DeliveryDate": form.get("deliveryDate", ""),
        "TotalAmount": total, "Status": "商談中", "Notes": form.get("notes", ""),
        "CreatedAt": form.get("orderDate", ""),
    }
    db.order_items[oid] = items
    return redirect_to(request, "/Order/List")


@app.post("/Order/Entry/{oid}")
async def order_update(request: Request, oid: str):
    form = await request.form()
    o = db.orders.get(oid)
    if not o:
        return redirect_to(request, "/Order/List")
    cust = db.customers.get(form.get("customerId"))
    items = parse_item_rows(form)
    total = sum(it["Amount"] for it in items)
    o.update({
        "CustomerId": cust["Id"] if cust else o["CustomerId"],
        "CustomerName": cust["Name"] if cust else o["CustomerName"],
        "OrderDate": form.get("orderDate", o["OrderDate"]),
        "DeliveryDate": form.get("deliveryDate", o["DeliveryDate"]),
        "TotalAmount": total, "Notes": form.get("notes", o["Notes"]),
    })
    db.orders[oid] = o  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    db.order_items[oid] = items
    return redirect_to(request, "/Order/List")


@app.get("/Order/Detail/{oid}")
def order_detail(request: Request, oid: str):
    o = db.orders.get(oid)
    if not o:
        return redirect_to(request, "/Order/List")
    fields = [
        field("CustomerName", "顧客名"), field("OrderDate", "受注日"), field("DeliveryDate", "納車予定日"),
        field("TotalAmount", "合計金額", "number"), field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="受注詳細", heading="受注詳細", entity_path="Order",
                          fields=fields, values=o, record_id=oid, items=db.order_items.get(oid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# Estimate（見積管理） — Orderと同構造
# ---------------------------------------------------------------------------
@app.get("/Estimate/List")
def estimate_list(request: Request):
    return render_list(request, title="見積一覧", heading="見積一覧", entity_path="Estimate",
                        columns=ESTIMATE_LIST_COLUMNS, rows=list(db.estimates.values()),
                        new_label="見積新規登録", money_fields={"TotalAmount"})


@app.get("/Estimate/Entry")
def estimate_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "見積入力", "heading": "見積入力", "entity_path": "Estimate",
        "partner_label": "顧客", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "見積日", "date1_name": "estimateDate", "date2_label": "有効期限", "date2_name": "validUntil",
        "products": vehicle_list(), "items": [], "values": {}, "is_edit": False,
        "total_elem_id": "estimate-total",
    })


@app.get("/Estimate/Entry/{eid}")
def estimate_entry_edit(request: Request, eid: str):
    e = db.estimates.get(eid)
    if not e:
        return redirect_to(request, "/Estimate/List")
    values = dict(e)
    values["customerId"] = e["CustomerId"]
    values["estimateDate"] = e["EstimateDate"]
    values["validUntil"] = e["ValidUntil"]
    values["_total"] = e["TotalAmount"]
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "見積編集", "heading": "見積編集", "entity_path": "Estimate",
        "partner_label": "顧客", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "見積日", "date1_name": "estimateDate", "date2_label": "有効期限", "date2_name": "validUntil",
        "products": vehicle_list(), "items": db.estimate_items.get(eid, []), "values": values,
        "is_edit": True, "record_id": eid, "total_elem_id": "estimate-total",
    })


@app.post("/Estimate/Entry")
async def estimate_create(request: Request):
    form = await request.form()
    cust = db.customers.get(form.get("customerId"))
    items = parse_item_rows(form)
    total = sum(it["Amount"] for it in items)
    eid = db.next_id("Estimate")
    db.estimates[eid] = {
        "Id": eid, "CustomerId": cust["Id"] if cust else "", "CustomerName": cust["Name"] if cust else "不明",
        "EstimateDate": form.get("estimateDate", ""), "ValidUntil": form.get("validUntil", ""),
        "TotalAmount": total, "Status": "作成中", "Notes": form.get("notes", ""),
        "CreatedAt": form.get("estimateDate", ""),
    }
    db.estimate_items[eid] = items
    return redirect_to(request, "/Estimate/List")


@app.post("/Estimate/Entry/{eid}")
async def estimate_update(request: Request, eid: str):
    form = await request.form()
    e = db.estimates.get(eid)
    if not e:
        return redirect_to(request, "/Estimate/List")
    cust = db.customers.get(form.get("customerId"))
    items = parse_item_rows(form)
    total = sum(it["Amount"] for it in items)
    e.update({
        "CustomerId": cust["Id"] if cust else e["CustomerId"],
        "CustomerName": cust["Name"] if cust else e["CustomerName"],
        "EstimateDate": form.get("estimateDate", e["EstimateDate"]),
        "ValidUntil": form.get("validUntil", e["ValidUntil"]),
        "TotalAmount": total, "Notes": form.get("notes", e["Notes"]),
    })
    db.estimates[eid] = e  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    db.estimate_items[eid] = items
    return redirect_to(request, "/Estimate/List")


@app.get("/Estimate/Detail/{eid}")
def estimate_detail(request: Request, eid: str):
    e = db.estimates.get(eid)
    if not e:
        return redirect_to(request, "/Estimate/List")
    fields = [
        field("CustomerName", "顧客名"), field("EstimateDate", "見積日"), field("ValidUntil", "有効期限"),
        field("TotalAmount", "合計金額", "number"), field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="見積詳細", heading="見積詳細", entity_path="Estimate",
                          fields=fields, values=e, record_id=eid, items=db.estimate_items.get(eid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# PurchaseOrder（仕入管理） — Orderと同構造（相手先=仕入先、対象=車両）
# ---------------------------------------------------------------------------
@app.get("/PurchaseOrder/List")
def po_list(request: Request):
    return render_list(request, title="仕入一覧", heading="仕入一覧", entity_path="PurchaseOrder",
                        columns=PO_LIST_COLUMNS, rows=list(db.purchase_orders.values()),
                        new_label="仕入新規登録", money_fields={"TotalAmount"})


@app.get("/PurchaseOrder/Entry")
def po_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "仕入入力", "heading": "仕入入力", "entity_path": "PurchaseOrder",
        "partner_label": "仕入先", "partner_field": "supplierId", "partner_options": supplier_options(),
        "date1_label": "仕入日", "date1_name": "orderDate", "date2_label": "入庫予定日", "date2_name": "deliveryDate",
        "products": vehicle_list(), "items": [], "values": {}, "is_edit": False,
        "total_elem_id": "purchaseorder-total",
    })


@app.get("/PurchaseOrder/Entry/{pid}")
def po_entry_edit(request: Request, pid: str):
    po = db.purchase_orders.get(pid)
    if not po:
        return redirect_to(request, "/PurchaseOrder/List")
    values = dict(po)
    values["supplierId"] = po["SupplierId"]
    values["orderDate"] = po["OrderDate"]
    values["deliveryDate"] = po["DeliveryDate"]
    values["_total"] = po["TotalAmount"]
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "仕入編集", "heading": "仕入編集", "entity_path": "PurchaseOrder",
        "partner_label": "仕入先", "partner_field": "supplierId", "partner_options": supplier_options(),
        "date1_label": "仕入日", "date1_name": "orderDate", "date2_label": "入庫予定日", "date2_name": "deliveryDate",
        "products": vehicle_list(), "items": db.purchase_order_items.get(pid, []), "values": values,
        "is_edit": True, "record_id": pid, "total_elem_id": "purchaseorder-total",
    })


@app.post("/PurchaseOrder/Entry")
async def po_create(request: Request):
    form = await request.form()
    sup = db.suppliers.get(form.get("supplierId"))
    items = parse_item_rows(form)
    total = sum(it["Amount"] for it in items)
    pid = db.next_id("PurchaseOrder")
    db.purchase_orders[pid] = {
        "Id": pid, "SupplierId": sup["Id"] if sup else "", "SupplierName": sup["Name"] if sup else "不明",
        "OrderDate": form.get("orderDate", ""), "DeliveryDate": form.get("deliveryDate", ""),
        "TotalAmount": total, "Status": "仕入交渉中", "Notes": form.get("notes", ""),
        "CreatedAt": form.get("orderDate", ""),
    }
    db.purchase_order_items[pid] = items
    return redirect_to(request, "/PurchaseOrder/List")


@app.post("/PurchaseOrder/Entry/{pid}")
async def po_update(request: Request, pid: str):
    form = await request.form()
    po = db.purchase_orders.get(pid)
    if not po:
        return redirect_to(request, "/PurchaseOrder/List")
    sup = db.suppliers.get(form.get("supplierId"))
    items = parse_item_rows(form)
    total = sum(it["Amount"] for it in items)
    po.update({
        "SupplierId": sup["Id"] if sup else po["SupplierId"],
        "SupplierName": sup["Name"] if sup else po["SupplierName"],
        "OrderDate": form.get("orderDate", po["OrderDate"]),
        "DeliveryDate": form.get("deliveryDate", po["DeliveryDate"]),
        "TotalAmount": total, "Notes": form.get("notes", po["Notes"]),
    })
    db.purchase_orders[pid] = po  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    db.purchase_order_items[pid] = items
    return redirect_to(request, "/PurchaseOrder/List")


@app.get("/PurchaseOrder/Detail/{pid}")
def po_detail(request: Request, pid: str):
    po = db.purchase_orders.get(pid)
    if not po:
        return redirect_to(request, "/PurchaseOrder/List")
    fields = [
        field("SupplierName", "仕入先"), field("OrderDate", "仕入日"), field("DeliveryDate", "入庫予定日"),
        field("TotalAmount", "合計金額", "number"), field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="仕入詳細", heading="仕入詳細", entity_path="PurchaseOrder",
                          fields=fields, values=po, record_id=pid, items=db.purchase_order_items.get(pid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# Invoice（請求管理） — 単純フォーム
# ---------------------------------------------------------------------------
def invoice_fields_with_options():
    fields = [dict(f) for f in INVOICE_FIELDS]
    for f in fields:
        if f["name"] == "CustomerId":
            f["options"] = [c["Id"] for c in db.customers.values()]
        if f["name"] == "OrderId":
            f["options"] = [""] + [o["Id"] for o in db.orders.values()]
    return fields


@app.get("/Invoice/List")
def invoice_list(request: Request):
    return render_list(request, title="請求一覧", heading="請求一覧", entity_path="Invoice",
                        columns=INVOICE_LIST_COLUMNS, rows=list(db.invoices.values()),
                        new_label="請求新規登録", money_fields={"TotalAmount"})


@app.get("/Invoice/Entry")
def invoice_entry_new(request: Request):
    return render_entry(request, title="請求新規登録", heading="請求新規登録", entity_path="Invoice",
                         fields=invoice_fields_with_options(), values={}, is_edit=False)


@app.get("/Invoice/Entry/{iid}")
def invoice_entry_edit(request: Request, iid: str):
    inv = db.invoices.get(iid)
    if not inv:
        return redirect_to(request, "/Invoice/List")
    return render_entry(request, title="請求編集", heading="請求編集", entity_path="Invoice",
                         fields=invoice_fields_with_options(), values=inv, is_edit=True, record_id=iid)


@app.post("/Invoice/Entry")
async def invoice_create(request: Request):
    form = await request.form()
    cust = db.customers.get(form.get("CustomerId"))
    iid = db.next_id("Invoice")
    db.invoices[iid] = {
        "Id": iid, "CustomerId": cust["Id"] if cust else "", "CustomerName": cust["Name"] if cust else "不明",
        "InvoiceDate": form.get("InvoiceDate", ""), "DueDate": form.get("DueDate", ""),
        "TotalAmount": int(form.get("TotalAmount") or 0), "Status": "未払い",
        "OrderId": form.get("OrderId", ""), "Notes": form.get("Notes", ""),
        "CreatedAt": form.get("InvoiceDate", ""),
    }
    return redirect_to(request, "/Invoice/List")


@app.post("/Invoice/Entry/{iid}")
async def invoice_update(request: Request, iid: str):
    form = await request.form()
    inv = db.invoices.get(iid)
    if not inv:
        return redirect_to(request, "/Invoice/List")
    cust = db.customers.get(form.get("CustomerId"))
    inv.update({
        "CustomerId": cust["Id"] if cust else inv["CustomerId"],
        "CustomerName": cust["Name"] if cust else inv["CustomerName"],
        "InvoiceDate": form.get("InvoiceDate", inv["InvoiceDate"]),
        "DueDate": form.get("DueDate", inv["DueDate"]),
        "TotalAmount": int(form.get("TotalAmount") or inv["TotalAmount"]),
        "OrderId": form.get("OrderId", inv["OrderId"]),
        "Notes": form.get("Notes", inv["Notes"]),
    })
    db.invoices[iid] = inv  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    return redirect_to(request, "/Invoice/List")


@app.get("/Invoice/Detail/{iid}")
def invoice_detail(request: Request, iid: str):
    inv = db.invoices.get(iid)
    if not inv:
        return redirect_to(request, "/Invoice/List")
    fields = [
        field("CustomerName", "顧客名"), field("InvoiceDate", "請求日"), field("DueDate", "支払期日"),
        field("TotalAmount", "金額", "number"), field("OrderId", "関連受注"),
        field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="請求詳細", heading="請求詳細", entity_path="Invoice",
                          fields=fields, values=inv, record_id=iid, money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# Supplier（仕入先管理）
# ---------------------------------------------------------------------------
@app.get("/Supplier/List")
def supplier_list(request: Request):
    return render_list(request, title="仕入先一覧", heading="仕入先一覧", entity_path="Supplier",
                        columns=SUPPLIER_LIST_COLUMNS, rows=list(db.suppliers.values()),
                        new_label="仕入先新規登録", money_fields={"CreditAmount"})


@app.get("/Supplier/Entry")
def supplier_entry_new(request: Request):
    return render_entry(request, title="仕入先新規登録", heading="仕入先新規登録", entity_path="Supplier",
                         fields=SUPPLIER_FIELDS, values={}, is_edit=False)


@app.get("/Supplier/Entry/{sid}")
def supplier_entry_edit(request: Request, sid: str):
    s = db.suppliers.get(sid)
    if not s:
        return redirect_to(request, "/Supplier/List")
    return render_entry(request, title="仕入先編集", heading="仕入先編集", entity_path="Supplier",
                         fields=SUPPLIER_FIELDS, values=s, is_edit=True, record_id=sid)


@app.post("/Supplier/Entry")
async def supplier_create(request: Request):
    form = await request.form()
    values = form_values(form, SUPPLIER_FIELDS)
    sid = db.next_id("Supplier")
    values.update({"Id": sid, "CreatedAt": db._rand_date(0, 0)})
    db.suppliers[sid] = values
    return redirect_to(request, "/Supplier/List")


@app.post("/Supplier/Entry/{sid}")
async def supplier_update(request: Request, sid: str):
    form = await request.form()
    values = form_values(form, SUPPLIER_FIELDS)
    existing = db.suppliers.get(sid, {})
    existing.update(values)
    existing["Id"] = sid
    db.suppliers[sid] = existing
    return redirect_to(request, "/Supplier/List")


@app.get("/Supplier/Detail/{sid}")
def supplier_detail(request: Request, sid: str):
    s = db.suppliers.get(sid)
    if not s:
        return redirect_to(request, "/Supplier/List")
    return render_detail(request, title="仕入先詳細", heading="仕入先詳細", entity_path="Supplier",
                          fields=SUPPLIER_FIELDS, values=s, record_id=sid, money_fields={"CreditAmount"})


# ---------------------------------------------------------------------------
# Employee（従業員管理）
# ---------------------------------------------------------------------------
@app.get("/Employee/List")
def employee_list(request: Request):
    return render_list(request, title="従業員一覧", heading="従業員一覧", entity_path="Employee",
                        columns=EMPLOYEE_LIST_COLUMNS, rows=list(db.employees.values()),
                        new_label="従業員新規登録")


@app.get("/Employee/Entry")
def employee_entry_new(request: Request):
    return render_entry(request, title="従業員新規登録", heading="従業員新規登録", entity_path="Employee",
                         fields=EMPLOYEE_FIELDS, values={}, is_edit=False)


@app.get("/Employee/Entry/{eid}")
def employee_entry_edit(request: Request, eid: str):
    e = db.employees.get(eid)
    if not e:
        return redirect_to(request, "/Employee/List")
    return render_entry(request, title="従業員編集", heading="従業員編集", entity_path="Employee",
                         fields=EMPLOYEE_FIELDS, values=e, is_edit=True, record_id=eid)


@app.post("/Employee/Entry")
async def employee_create(request: Request):
    form = await request.form()
    values = form_values(form, EMPLOYEE_FIELDS)
    eid = db.next_id("Employee")
    values.update({"Id": eid, "CreatedAt": db._rand_date(0, 0)})
    db.employees[eid] = values
    return redirect_to(request, "/Employee/List")


@app.post("/Employee/Entry/{eid}")
async def employee_update(request: Request, eid: str):
    form = await request.form()
    values = form_values(form, EMPLOYEE_FIELDS)
    existing = db.employees.get(eid, {})
    existing.update(values)
    existing["Id"] = eid
    db.employees[eid] = existing
    return redirect_to(request, "/Employee/List")


@app.get("/Employee/Detail/{eid}")
def employee_detail(request: Request, eid: str):
    e = db.employees.get(eid)
    if not e:
        return redirect_to(request, "/Employee/List")
    return render_detail(request, title="従業員詳細", heading="従業員詳細", entity_path="Employee",
                          fields=EMPLOYEE_FIELDS, values=e, record_id=eid)


# ---------------------------------------------------------------------------
# Vehicle / Stock（車両在庫照会） — 照会のみ（元ERPの Product/Inquiry に相当）
# ---------------------------------------------------------------------------
@app.get("/Vehicle/Inquiry")
def vehicle_inquiry(request: Request):
    return templates.TemplateResponse(request, "vehicle_inquiry.html",
                                       {"title": "車両在庫照会", "vehicles": list(db.vehicles.values())})


@app.get("/Stock/Inquiry")
def stock_inquiry(request: Request):
    return vehicle_inquiry(request)


# ---------------------------------------------------------------------------
# InventoryTransaction（車両入出庫履歴） — 一覧のみ
# ---------------------------------------------------------------------------
@app.get("/InventoryTransaction/List")
def inventory_transaction_list(request: Request):
    rows = sorted(db.inventory_transactions, key=lambda r: r["Date"], reverse=True)
    return render_list(request, title="車両入出庫履歴", heading="車両入出庫履歴",
                        entity_path="InventoryTransaction", columns=INVTX_LIST_COLUMNS, rows=rows,
                        show_entry=False, show_detail=False)


# ---------------------------------------------------------------------------
# GoodsReceipt（入庫管理） — 一覧＋登録
# ---------------------------------------------------------------------------
def goodsreceipt_fields_with_options():
    fields = [dict(f) for f in GOODSRECEIPT_FIELDS]
    for f in fields:
        if f["name"] == "SupplierId":
            f["options"] = [s["Id"] for s in db.suppliers.values()]
        if f["name"] == "ProductId":
            f["options"] = [v["Id"] for v in db.vehicles.values()]
    return fields


@app.get("/GoodsReceipt/List")
def goodsreceipt_list(request: Request):
    return render_list(request, title="入庫一覧", heading="入庫一覧", entity_path="GoodsReceipt",
                        columns=GOODSRECEIPT_LIST_COLUMNS, rows=list(db.goods_receipts.values()),
                        show_detail=False, new_label="入庫登録")


@app.get("/GoodsReceipt/Entry")
def goodsreceipt_entry_new(request: Request):
    return render_entry(request, title="入庫登録", heading="入庫登録", entity_path="GoodsReceipt",
                         fields=goodsreceipt_fields_with_options(), values={}, is_edit=False)


@app.post("/GoodsReceipt/Entry")
async def goodsreceipt_create(request: Request):
    form = await request.form()
    sup = db.suppliers.get(form.get("SupplierId"))
    prod = db.vehicles.get(form.get("ProductId"))
    gid = db.next_id("GoodsReceipt")
    db.goods_receipts[gid] = {
        "Id": gid, "SupplierId": sup["Id"] if sup else "", "SupplierName": sup["Name"] if sup else "不明",
        "ProductId": prod["Id"] if prod else "", "ProductName": prod["Name"] if prod else "不明",
        "Quantity": int(form.get("Quantity") or 0), "ReceiptDate": form.get("ReceiptDate", ""),
    }
    if prod:
        prod["Stock"] += int(form.get("Quantity") or 0)
        db.vehicles[prod["Id"]] = prod  # SQLite永続化(インプレース変更はwrite-throughされないため再代入)
    return redirect_to(request, "/GoodsReceipt/List")


# ---------------------------------------------------------------------------
# ServiceOrder（整備/車検管理） — 自動車ディーラー特有の新設エンティティ
# ---------------------------------------------------------------------------
def serviceorder_fields_with_options():
    fields = [dict(f) for f in SERVICEORDER_FIELDS]
    for f in fields:
        if f["name"] == "CustomerId":
            f["options"] = [c["Id"] for c in db.customers.values()]
        if f["name"] == "VehicleId":
            f["options"] = [v["Id"] for v in db.vehicles.values()]
    return fields


@app.get("/ServiceOrder/List")
def serviceorder_list(request: Request):
    return render_list(request, title="整備/車検一覧", heading="整備/車検一覧", entity_path="ServiceOrder",
                        columns=SERVICEORDER_LIST_COLUMNS, rows=list(db.service_orders.values()),
                        new_label="整備入庫登録", money_fields={"Cost"})


@app.get("/ServiceOrder/Entry")
def serviceorder_entry_new(request: Request):
    return render_entry(request, title="整備入庫登録", heading="整備入庫登録", entity_path="ServiceOrder",
                         fields=serviceorder_fields_with_options(), values={}, is_edit=False)


@app.get("/ServiceOrder/Entry/{svid}")
def serviceorder_entry_edit(request: Request, svid: str):
    sv = db.service_orders.get(svid)
    if not sv:
        return redirect_to(request, "/ServiceOrder/List")
    return render_entry(request, title="整備編集", heading="整備編集", entity_path="ServiceOrder",
                         fields=serviceorder_fields_with_options(), values=sv, is_edit=True, record_id=svid)


@app.post("/ServiceOrder/Entry")
async def serviceorder_create(request: Request):
    form = await request.form()
    cust = db.customers.get(form.get("CustomerId"))
    veh = db.vehicles.get(form.get("VehicleId"))
    svid = db.next_id("ServiceOrder")
    db.service_orders[svid] = {
        "Id": svid, "CustomerId": cust["Id"] if cust else "", "CustomerName": cust["Name"] if cust else "不明",
        "VehicleId": veh["Id"] if veh else "", "VehicleName": veh["Name"] if veh else "不明",
        "ServiceType": form.get("ServiceType", ""), "ServiceDate": form.get("ServiceDate", ""),
        "Cost": int(form.get("Cost") or 0), "Mechanic": form.get("Mechanic", ""),
        "Status": form.get("Status") or "予約", "Notes": form.get("Notes", ""),
        "CreatedAt": form.get("ServiceDate", ""),
    }
    return redirect_to(request, "/ServiceOrder/List")


@app.post("/ServiceOrder/Entry/{svid}")
async def serviceorder_update(request: Request, svid: str):
    form = await request.form()
    sv = db.service_orders.get(svid)
    if not sv:
        return redirect_to(request, "/ServiceOrder/List")
    cust = db.customers.get(form.get("CustomerId"))
    veh = db.vehicles.get(form.get("VehicleId"))
    sv.update({
        "CustomerId": cust["Id"] if cust else sv["CustomerId"],
        "CustomerName": cust["Name"] if cust else sv["CustomerName"],
        "VehicleId": veh["Id"] if veh else sv["VehicleId"],
        "VehicleName": veh["Name"] if veh else sv["VehicleName"],
        "ServiceType": form.get("ServiceType", sv["ServiceType"]),
        "ServiceDate": form.get("ServiceDate", sv["ServiceDate"]),
        "Cost": int(form.get("Cost") or sv["Cost"]),
        "Mechanic": form.get("Mechanic", sv["Mechanic"]),
        "Status": form.get("Status", sv["Status"]),
        "Notes": form.get("Notes", sv["Notes"]),
    })
    db.service_orders[svid] = sv  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    return redirect_to(request, "/ServiceOrder/List")


@app.get("/ServiceOrder/Detail/{svid}")
def serviceorder_detail(request: Request, svid: str):
    sv = db.service_orders.get(svid)
    if not sv:
        return redirect_to(request, "/ServiceOrder/List")
    fields = [
        field("CustomerName", "顧客名"), field("VehicleName", "車両"), field("ServiceType", "整備種別"),
        field("ServiceDate", "整備日"), field("Cost", "費用", "number"), field("Mechanic", "担当整備士"),
        field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="整備詳細", heading="整備詳細", entity_path="ServiceOrder",
                          fields=fields, values=sv, record_id=svid, money_fields={"Cost"})


# ---------------------------------------------------------------------------
# ArAp（売掛買掛） — 一覧のみ
# ---------------------------------------------------------------------------
@app.get("/ArAp/List")
def arap_list(request: Request):
    return templates.TemplateResponse(request, "arap_list.html",
                                       {"title": "売掛買掛一覧", "rows": db.build_arap()})


# ---------------------------------------------------------------------------
# Profit（利益管理） — 一覧のみ
# ---------------------------------------------------------------------------
@app.get("/Profit/List")
def profit_list(request: Request):
    return templates.TemplateResponse(request, "profit_list.html",
                                       {"title": "利益管理", "rows": db.build_profit()})


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5020, reload=True)
