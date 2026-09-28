"""
デモ・レガシーシステム（不動産仲介版, localhost:5030）
======================================================
AI機能ゼロの模擬WebForms風・不動産仲介基幹システム。全13業務エンティティ
（Customer/Order(契約)/Property/Supplier(協力会社)/Employee(担当エージェント)/
Estimate(査定)/Invoice(仲介手数料請求)/PurchaseOrder(工事発注)/
InventoryTransaction(物件ステータス履歴)/GoodsReceipt(工事完了報告)/
Viewing(内見予約)/ArAp/Profit）に対応するサーバーサイドHTMLレンダリング
（Jinja2）画面群。

demo-legacy-system（製造業ERP版）と全く同じ設計を、不動産仲介の業務ドメインに
適用したもの。「既存のレガシーシステムを一切変更せずにAI機能を付与する」という
AI-Sync Bridge のコンセプトが、業種を問わず同じ仕組み（aisb_embed のミドルウェア
注入 + 読み取り専用JSON API）で成立することを示す3つ目のデモ（demo-legacy-system
= 製造業ERP、demo-legacy-system-dealer = 自動車ディーラー、本デモ = 不動産仲介）。

元ERPとの主な差分（設計判断）:
  - Product（商品/在庫）を廃止し、Property（物件）を明細行の対象に昇格。
    元ERP版のPropertyは独立マスタで受注/見積と未連携だったが、本デモでは
    Order(契約)/Estimate(査定)の明細行が実際にPropertyを参照する構造にした
    （「不動産仲介の中核＝物件」という業務実態に合わせた接続）。
  - PurchaseOrder（発注）は「工事発注」として、Property明細とは別カタログ
    （RENOVATION_SERVICES）を明細行対象にする（協力会社へのリフォーム等発注
    と、物件そのものの売買は別業務のため）。
  - Viewing（内見予約）を新設。元ERPには存在しない、日程調整・実施記録という
    ワークフロー色の強いエンティティを追加できることを示すデモを兼ねる
    （dealer版のServiceOrder新設と同じ位置づけ）。

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

app = FastAPI(title="Real Estate Agency Legacy System (Demo)")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# サブパス経由公開(例: https://host/realestate/... 経由でCaddyがstrip_prefixする構成)対応。
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
    field("CustomerType", "顧客区分", "select", ["買主", "売主", "買主・売主"]),
    field("PostalCode", "郵便番号"),
    field("Address", "住所"),
    field("Tel", "TEL"),
    field("Email", "メール"),
    field("DesiredArea", "希望エリア"),
    field("Budget", "予算", "number"),
    field("CreditLimit", "ローン事前審査枠", "number"),
    field("Notes", "備考", "textarea"),
]
CUSTOMER_LIST_COLUMNS = [
    ("Id", "ID"), ("Name", "氏名/会社名"), ("CustomerType", "区分"), ("Tel", "TEL"),
    ("CreditLimit", "ローン事前審査枠"), ("CreditRate", "利用率"),
]

SUPPLIER_FIELDS = [
    field("Name", "協力会社名", required=True),
    field("Category", "業務区分", "select", db.SUPPLIER_CATEGORIES),
    field("Tel", "TEL"),
    field("Address", "住所"),
    field("ContactPerson", "担当者"),
    field("CreditAmount", "取引限度額", "number"),
    field("PaymentTerms", "支払条件"),
    field("Notes", "備考", "textarea"),
]
SUPPLIER_LIST_COLUMNS = [
    ("Id", "ID"), ("Name", "協力会社名"), ("Category", "業務区分"), ("Tel", "TEL"),
    ("ContactPerson", "担当者"), ("CreditAmount", "取引限度額"),
]

EMPLOYEE_FIELDS = [
    field("Name", "氏名", required=True),
    field("Department", "部署", "select", db.DEPARTMENTS),
    field("Position", "役職", "select", db.POSITIONS),
    field("LicenseNo", "宅地建物取引士証番号"),
    field("Email", "メール"),
    field("Tel", "TEL"),
    field("HireDate", "入社日", "date"),
]
EMPLOYEE_LIST_COLUMNS = [
    ("Id", "ID"), ("Name", "氏名"), ("Department", "部署"), ("Position", "役職"),
    ("LicenseNo", "宅建士証番号"), ("Tel", "TEL"),
]

PROPERTY_FIELDS = [
    field("Name", "物件名", required=True),
    field("NameKana", "フリガナ"),
    field("PropertyType", "種別", "select", db.PROPERTY_TYPES),
    field("TransactionType", "取引態様", "select", db.TRANSACTION_TYPES),
    field("OwnerId", "売主(顧客)", "select"),  # options injected per-request
    field("Status", "ステータス", "select", db.PROPERTY_STATUSES),
    field("Address", "住所"),
    field("Access", "交通"),
    field("LandArea", "敷地面積", "number"),
    field("BuildingArea", "建物面積", "number"),
    field("Structure", "構造"),
    field("Floors", "階数", "number"),
    field("BuiltDate", "築年月", "date"),
    field("LandRight", "権利形態"),
    field("Price", "価格", "number", required=True),
    field("MonthlyRent", "月額賃料", "number"),
    field("Facilities", "設備", "textarea"),
]
PROPERTY_LIST_COLUMNS = [
    ("Id", "ID"), ("Name", "物件名"), ("PropertyType", "種別"), ("Address", "住所"),
    ("Price", "価格"), ("Status", "ステータス"),
]

INVOICE_FIELDS = [
    field("CustomerId", "顧客", "select", required=True),  # options injected per-request
    field("InvoiceDate", "請求日", "date"),
    field("DueDate", "支払期日", "date"),
    field("TotalAmount", "金額", "number", required=True),
    field("OrderId", "関連契約", "select"),
    field("Notes", "備考", "textarea"),
]
INVOICE_LIST_COLUMNS = [
    ("Id", "請求番号"), ("CustomerName", "顧客名"), ("InvoiceDate", "請求日"),
    ("DueDate", "支払期日"), ("TotalAmount", "金額"), ("Status", "ステータス"),
]

GOODSRECEIPT_FIELDS = [
    field("SupplierId", "協力会社", "select", required=True),
    field("PropertyId", "対象物件", "select", required=True),
    field("WorkDescription", "工事内容"),
    field("ReceiptDate", "完了日", "date"),
]
GOODSRECEIPT_LIST_COLUMNS = [
    ("Id", "ID"), ("SupplierName", "協力会社"), ("PropertyName", "対象物件"),
    ("WorkDescription", "工事内容"), ("ReceiptDate", "完了日"),
]

VIEWING_FIELDS = [
    field("CustomerId", "顧客", "select", required=True),
    field("PropertyId", "物件", "select", required=True),
    field("EmployeeId", "担当エージェント", "select"),
    field("ViewingDate", "内見日", "date", required=True),
    field("Status", "ステータス", "select", db.VIEWING_STATUSES),
    field("Feedback", "所見/フィードバック", "textarea"),
]
VIEWING_LIST_COLUMNS = [
    ("Id", "内見番号"), ("CustomerName", "顧客名"), ("PropertyName", "物件"),
    ("ViewingDate", "内見日"), ("Status", "ステータス"),
]

ORDER_LIST_COLUMNS = [
    ("Id", "契約ID"), ("CustomerName", "顧客名"), ("OrderDate", "契約日"),
    ("DeliveryDate", "引渡予定日"), ("TotalAmount", "契約金額"), ("Status", "ステータス"), ("Notes", "備考"),
]
ESTIMATE_LIST_COLUMNS = [
    ("Id", "査定番号"), ("CustomerName", "顧客名"), ("EstimateDate", "査定日"),
    ("ValidUntil", "有効期限"), ("TotalAmount", "査定額"), ("Status", "ステータス"),
]
PO_LIST_COLUMNS = [
    ("Id", "発注番号"), ("SupplierName", "協力会社"), ("OrderDate", "発注日"),
    ("DeliveryDate", "完了予定日"), ("TotalAmount", "合計金額"), ("Status", "ステータス"),
]
INVTX_LIST_COLUMNS = [
    ("ProductName", "物件"), ("Type", "ステータス変化"), ("Date", "日付"), ("Notes", "備考"),
]


def customer_options():
    return [(c["Id"], c["Name"]) for c in db.customers.values()]


def supplier_options():
    return [(s["Id"], s["Name"]) for s in db.suppliers.values()]


def property_list():
    return list(db.property_catalog().values())


def renovation_list():
    return list(db.RENOVATION_SERVICES)


# ---------------------------------------------------------------------------
# JSON API（AI-Sync Bridge 連携用・読み取り専用。demo-legacy-systemと同一設計）
# ---------------------------------------------------------------------------
ENTITY_LABELS = {
    "Customer": "顧客", "Order": "契約", "Property": "物件", "Supplier": "協力会社",
    "Employee": "担当エージェント", "Estimate": "査定", "Invoice": "請求", "PurchaseOrder": "工事発注",
    "InventoryTransaction": "物件ステータス履歴", "GoodsReceipt": "工事完了報告",
    "Viewing": "内見予約", "ArAp": "売掛買掛", "Profit": "利益",
}

_ENTITY_ROWS = {
    "Customer": lambda: list(db.customers.values()),
    "Order": lambda: list(db.orders.values()),
    "Property": lambda: list(db.properties.values()),
    "Supplier": lambda: list(db.suppliers.values()),
    "Employee": lambda: list(db.employees.values()),
    "Estimate": lambda: list(db.estimates.values()),
    "Invoice": lambda: list(db.invoices.values()),
    "PurchaseOrder": lambda: list(db.purchase_orders.values()),
    "InventoryTransaction": lambda: list(db.inventory_transactions),
    "GoodsReceipt": lambda: list(db.goods_receipts.values()),
    "Viewing": lambda: list(db.viewings.values()),
    "ArAp": lambda: db.build_arap(),
    "Profit": lambda: db.build_profit(),
}

_ENTITY_STORE = {
    "Customer": db.customers, "Order": db.orders, "Property": db.properties, "Supplier": db.suppliers,
    "Employee": db.employees, "Estimate": db.estimates, "Invoice": db.invoices,
    "PurchaseOrder": db.purchase_orders, "Viewing": db.viewings,
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
        "properties": len(db.properties),
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
# Order（契約管理: 売買/賃貸） — 明細行グリッド付き（最重要画面）
# 明細行の対象は Property（物件）。1契約=1物件が基本だが、engine自体は複数行を
# 許容する汎用実装のまま(demo-legacy-systemと同じ)。
# ---------------------------------------------------------------------------
def parse_item_rows(form, catalog):
    ids = form.getlist("productId")
    quantities = form.getlist("quantity")
    items = []
    for pid, qty in zip(ids, quantities):
        if not pid:
            continue
        p = catalog.get(pid)
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
    return render_list(request, title="契約一覧", heading="契約一覧", entity_path="Order",
                        columns=ORDER_LIST_COLUMNS, rows=list(db.orders.values()), show_search=False,
                        new_label="契約新規登録", money_fields={"TotalAmount"})


@app.get("/Order/Entry")
def order_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "契約入力", "heading": "契約入力", "entity_path": "Order",
        "partner_label": "顧客", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "契約日", "date1_name": "orderDate", "date2_label": "引渡予定日", "date2_name": "deliveryDate",
        "products": property_list(), "items": [], "values": {}, "is_edit": False,
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
        "title": "契約編集", "heading": "契約編集", "entity_path": "Order",
        "partner_label": "顧客", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "契約日", "date1_name": "orderDate", "date2_label": "引渡予定日", "date2_name": "deliveryDate",
        "products": property_list(), "items": db.order_items.get(oid, []), "values": values,
        "is_edit": True, "record_id": oid, "total_elem_id": "order-total",
    })


@app.post("/Order/Entry")
async def order_create(request: Request):
    form = await request.form()
    cust = db.customers.get(form.get("customerId"))
    items = parse_item_rows(form, db.property_catalog())
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
    items = parse_item_rows(form, db.property_catalog())
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
        field("CustomerName", "顧客名"), field("OrderDate", "契約日"), field("DeliveryDate", "引渡予定日"),
        field("TotalAmount", "契約金額", "number"), field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="契約詳細", heading="契約詳細", entity_path="Order",
                          fields=fields, values=o, record_id=oid, items=db.order_items.get(oid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# Estimate（査定管理: 売却査定書） — Orderと同構造
# ---------------------------------------------------------------------------
@app.get("/Estimate/List")
def estimate_list(request: Request):
    return render_list(request, title="査定一覧", heading="査定一覧", entity_path="Estimate",
                        columns=ESTIMATE_LIST_COLUMNS, rows=list(db.estimates.values()),
                        new_label="査定新規登録", money_fields={"TotalAmount"})


@app.get("/Estimate/Entry")
def estimate_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "査定入力", "heading": "査定入力", "entity_path": "Estimate",
        "partner_label": "顧客(売主)", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "査定日", "date1_name": "estimateDate", "date2_label": "有効期限", "date2_name": "validUntil",
        "products": property_list(), "items": [], "values": {}, "is_edit": False,
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
        "title": "査定編集", "heading": "査定編集", "entity_path": "Estimate",
        "partner_label": "顧客(売主)", "partner_field": "customerId", "partner_options": customer_options(),
        "date1_label": "査定日", "date1_name": "estimateDate", "date2_label": "有効期限", "date2_name": "validUntil",
        "products": property_list(), "items": db.estimate_items.get(eid, []), "values": values,
        "is_edit": True, "record_id": eid, "total_elem_id": "estimate-total",
    })


@app.post("/Estimate/Entry")
async def estimate_create(request: Request):
    form = await request.form()
    cust = db.customers.get(form.get("customerId"))
    items = parse_item_rows(form, db.property_catalog())
    total = sum(it["Amount"] for it in items)
    eid = db.next_id("Estimate")
    db.estimates[eid] = {
        "Id": eid, "CustomerId": cust["Id"] if cust else "", "CustomerName": cust["Name"] if cust else "不明",
        "EstimateDate": form.get("estimateDate", ""), "ValidUntil": form.get("validUntil", ""),
        "TotalAmount": total, "Status": "査定中", "Notes": form.get("notes", ""),
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
    items = parse_item_rows(form, db.property_catalog())
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
        field("CustomerName", "顧客名"), field("EstimateDate", "査定日"), field("ValidUntil", "有効期限"),
        field("TotalAmount", "査定額", "number"), field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="査定詳細", heading="査定詳細", entity_path="Estimate",
                          fields=fields, values=e, record_id=eid, items=db.estimate_items.get(eid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# PurchaseOrder（工事発注管理） — Orderと同構造（相手先=協力会社、対象=施工項目カタログ）
# ---------------------------------------------------------------------------
@app.get("/PurchaseOrder/List")
def po_list(request: Request):
    return render_list(request, title="工事発注一覧", heading="工事発注一覧", entity_path="PurchaseOrder",
                        columns=PO_LIST_COLUMNS, rows=list(db.purchase_orders.values()),
                        new_label="工事発注新規登録", money_fields={"TotalAmount"})


@app.get("/PurchaseOrder/Entry")
def po_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "工事発注入力", "heading": "工事発注入力", "entity_path": "PurchaseOrder",
        "partner_label": "協力会社", "partner_field": "supplierId", "partner_options": supplier_options(),
        "date1_label": "発注日", "date1_name": "orderDate", "date2_label": "完了予定日", "date2_name": "deliveryDate",
        "products": renovation_list(), "items": [], "values": {}, "is_edit": False,
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
        "title": "工事発注編集", "heading": "工事発注編集", "entity_path": "PurchaseOrder",
        "partner_label": "協力会社", "partner_field": "supplierId", "partner_options": supplier_options(),
        "date1_label": "発注日", "date1_name": "orderDate", "date2_label": "完了予定日", "date2_name": "deliveryDate",
        "products": renovation_list(), "items": db.purchase_order_items.get(pid, []), "values": values,
        "is_edit": True, "record_id": pid, "total_elem_id": "purchaseorder-total",
    })


@app.post("/PurchaseOrder/Entry")
async def po_create(request: Request):
    form = await request.form()
    sup = db.suppliers.get(form.get("supplierId"))
    items = parse_item_rows(form, db.renovation_catalog())
    total = sum(it["Amount"] for it in items)
    pid = db.next_id("PurchaseOrder")
    db.purchase_orders[pid] = {
        "Id": pid, "SupplierId": sup["Id"] if sup else "", "SupplierName": sup["Name"] if sup else "不明",
        "OrderDate": form.get("orderDate", ""), "DeliveryDate": form.get("deliveryDate", ""),
        "TotalAmount": total, "Status": "発注中", "Notes": form.get("notes", ""),
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
    items = parse_item_rows(form, db.renovation_catalog())
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
        field("SupplierName", "協力会社"), field("OrderDate", "発注日"), field("DeliveryDate", "完了予定日"),
        field("TotalAmount", "合計金額", "number"), field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="工事発注詳細", heading="工事発注詳細", entity_path="PurchaseOrder",
                          fields=fields, values=po, record_id=pid, items=db.purchase_order_items.get(pid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# Invoice（仲介手数料請求管理） — 単純フォーム
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
        "TotalAmount": int(form.get("TotalAmount") or 0), "Status": "未回収",
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
        field("TotalAmount", "金額", "number"), field("OrderId", "関連契約"),
        field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="請求詳細", heading="請求詳細", entity_path="Invoice",
                          fields=fields, values=inv, record_id=iid, money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# Supplier（協力会社管理）
# ---------------------------------------------------------------------------
@app.get("/Supplier/List")
def supplier_list(request: Request):
    return render_list(request, title="協力会社一覧", heading="協力会社一覧", entity_path="Supplier",
                        columns=SUPPLIER_LIST_COLUMNS, rows=list(db.suppliers.values()),
                        new_label="協力会社新規登録", money_fields={"CreditAmount"})


@app.get("/Supplier/Entry")
def supplier_entry_new(request: Request):
    return render_entry(request, title="協力会社新規登録", heading="協力会社新規登録", entity_path="Supplier",
                         fields=SUPPLIER_FIELDS, values={}, is_edit=False)


@app.get("/Supplier/Entry/{sid}")
def supplier_entry_edit(request: Request, sid: str):
    s = db.suppliers.get(sid)
    if not s:
        return redirect_to(request, "/Supplier/List")
    return render_entry(request, title="協力会社編集", heading="協力会社編集", entity_path="Supplier",
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
    return render_detail(request, title="協力会社詳細", heading="協力会社詳細", entity_path="Supplier",
                          fields=SUPPLIER_FIELDS, values=s, record_id=sid, money_fields={"CreditAmount"})


# ---------------------------------------------------------------------------
# Employee（担当エージェント管理）
# ---------------------------------------------------------------------------
@app.get("/Employee/List")
def employee_list(request: Request):
    return render_list(request, title="担当エージェント一覧", heading="担当エージェント一覧", entity_path="Employee",
                        columns=EMPLOYEE_LIST_COLUMNS, rows=list(db.employees.values()),
                        new_label="担当エージェント新規登録")


@app.get("/Employee/Entry")
def employee_entry_new(request: Request):
    return render_entry(request, title="担当エージェント新規登録", heading="担当エージェント新規登録", entity_path="Employee",
                         fields=EMPLOYEE_FIELDS, values={}, is_edit=False)


@app.get("/Employee/Entry/{eid}")
def employee_entry_edit(request: Request, eid: str):
    e = db.employees.get(eid)
    if not e:
        return redirect_to(request, "/Employee/List")
    return render_entry(request, title="担当エージェント編集", heading="担当エージェント編集", entity_path="Employee",
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
    return render_detail(request, title="担当エージェント詳細", heading="担当エージェント詳細", entity_path="Employee",
                          fields=EMPLOYEE_FIELDS, values=e, record_id=eid)


# ---------------------------------------------------------------------------
# Property（物件管理） — Entry と Register は別URLだが同一フォーム
# ---------------------------------------------------------------------------
def property_fields_with_options():
    fields = [dict(f) for f in PROPERTY_FIELDS]
    for f in fields:
        if f["name"] == "OwnerId":
            f["options"] = [c["Id"] for c in db.customers.values()]
    return fields


@app.get("/Property/List")
def property_list_view(request: Request):
    return render_list(request, title="物件一覧", heading="物件一覧", entity_path="Property",
                        columns=PROPERTY_LIST_COLUMNS, rows=list(db.properties.values()),
                        new_label="物件新規登録", money_fields={"Price"})


def _property_entry_response(request, title, heading, values, is_edit, record_id=None):
    return render_entry(request, title=title, heading=heading, entity_path="Property",
                         fields=property_fields_with_options(), values=values, is_edit=is_edit, record_id=record_id)


@app.get("/Property/Entry")
def property_entry_new(request: Request):
    return _property_entry_response(request, "物件新規登録", "物件新規登録", {}, False)


@app.get("/Property/Register")
def property_register(request: Request):
    return _property_entry_response(request, "物件新規登録", "物件新規登録（現地登録）", {}, False)


@app.get("/Property/Entry/{pid}")
def property_entry_edit(request: Request, pid: str):
    p = db.properties.get(pid)
    if not p:
        return redirect_to(request, "/Property/List")
    return _property_entry_response(request, "物件編集", "物件編集", p, True, pid)


@app.post("/Property/Entry")
async def property_create(request: Request):
    form = await request.form()
    values = form_values(form, PROPERTY_FIELDS)
    owner = db.customers.get(values.get("OwnerId"))
    pid = db.next_id("Property")
    values.update({"Id": pid, "OwnerName": owner["Name"] if owner else "", "OccupancyRate": 0,
                   "ParkingSpaces": 0, "CreatedAt": db._rand_date(0, 0)})
    db.properties[pid] = values
    return redirect_to(request, "/Property/List")


@app.post("/Property/Register")
async def property_register_submit(request: Request):
    return await property_create(request)


@app.post("/Property/Entry/{pid}")
async def property_update(request: Request, pid: str):
    form = await request.form()
    values = form_values(form, PROPERTY_FIELDS)
    owner = db.customers.get(values.get("OwnerId"))
    existing = db.properties.get(pid, {})
    existing.update(values)
    existing["Id"] = pid
    existing["OwnerName"] = owner["Name"] if owner else existing.get("OwnerName", "")
    db.properties[pid] = existing
    return redirect_to(request, "/Property/List")


@app.get("/Property/Detail/{pid}")
def property_detail(request: Request, pid: str):
    p = db.properties.get(pid)
    if not p:
        return redirect_to(request, "/Property/List")
    return render_detail(request, title="物件詳細", heading="物件詳細", entity_path="Property",
                          fields=PROPERTY_FIELDS, values=p, record_id=pid, money_fields={"Price"})


# ---------------------------------------------------------------------------
# InventoryTransaction（物件ステータス履歴） — 一覧のみ。元ERPの在庫トランザクション
# に相当し、物件が募集開始/内見受付/商談/契約/取り下げと状態遷移した記録を保持する。
# ---------------------------------------------------------------------------
@app.get("/InventoryTransaction/List")
def inventory_transaction_list(request: Request):
    rows = sorted(db.inventory_transactions, key=lambda r: r["Date"], reverse=True)
    return render_list(request, title="物件ステータス履歴", heading="物件ステータス履歴",
                        entity_path="InventoryTransaction", columns=INVTX_LIST_COLUMNS, rows=rows,
                        show_entry=False, show_detail=False)


# ---------------------------------------------------------------------------
# GoodsReceipt（工事完了報告） — 一覧＋登録
# ---------------------------------------------------------------------------
def goodsreceipt_fields_with_options():
    fields = [dict(f) for f in GOODSRECEIPT_FIELDS]
    for f in fields:
        if f["name"] == "SupplierId":
            f["options"] = [s["Id"] for s in db.suppliers.values()]
        if f["name"] == "PropertyId":
            f["options"] = [p["Id"] for p in db.properties.values()]
    return fields


@app.get("/GoodsReceipt/List")
def goodsreceipt_list(request: Request):
    return render_list(request, title="工事完了報告一覧", heading="工事完了報告一覧", entity_path="GoodsReceipt",
                        columns=GOODSRECEIPT_LIST_COLUMNS, rows=list(db.goods_receipts.values()),
                        show_detail=False, new_label="工事完了登録")


@app.get("/GoodsReceipt/Entry")
def goodsreceipt_entry_new(request: Request):
    return render_entry(request, title="工事完了登録", heading="工事完了登録", entity_path="GoodsReceipt",
                         fields=goodsreceipt_fields_with_options(), values={}, is_edit=False)


@app.post("/GoodsReceipt/Entry")
async def goodsreceipt_create(request: Request):
    form = await request.form()
    sup = db.suppliers.get(form.get("SupplierId"))
    prop = db.properties.get(form.get("PropertyId"))
    gid = db.next_id("GoodsReceipt")
    db.goods_receipts[gid] = {
        "Id": gid, "SupplierId": sup["Id"] if sup else "", "SupplierName": sup["Name"] if sup else "不明",
        "PropertyId": prop["Id"] if prop else "", "PropertyName": prop["Name"] if prop else "不明",
        "WorkDescription": form.get("WorkDescription", ""), "ReceiptDate": form.get("ReceiptDate", ""),
    }
    return redirect_to(request, "/GoodsReceipt/List")


# ---------------------------------------------------------------------------
# Viewing（内見予約管理） — 不動産仲介特有の新設エンティティ
# ---------------------------------------------------------------------------
def viewing_fields_with_options():
    fields = [dict(f) for f in VIEWING_FIELDS]
    for f in fields:
        if f["name"] == "CustomerId":
            f["options"] = [c["Id"] for c in db.customers.values()]
        if f["name"] == "PropertyId":
            f["options"] = [p["Id"] for p in db.properties.values()]
        if f["name"] == "EmployeeId":
            f["options"] = [""] + [e["Id"] for e in db.employees.values()]
    return fields


@app.get("/Viewing/List")
def viewing_list(request: Request):
    return render_list(request, title="内見予約一覧", heading="内見予約一覧", entity_path="Viewing",
                        columns=VIEWING_LIST_COLUMNS, rows=list(db.viewings.values()),
                        new_label="内見予約登録")


@app.get("/Viewing/Entry")
def viewing_entry_new(request: Request):
    return render_entry(request, title="内見予約登録", heading="内見予約登録", entity_path="Viewing",
                         fields=viewing_fields_with_options(), values={}, is_edit=False)


@app.get("/Viewing/Entry/{vid}")
def viewing_entry_edit(request: Request, vid: str):
    v = db.viewings.get(vid)
    if not v:
        return redirect_to(request, "/Viewing/List")
    return render_entry(request, title="内見予約編集", heading="内見予約編集", entity_path="Viewing",
                         fields=viewing_fields_with_options(), values=v, is_edit=True, record_id=vid)


@app.post("/Viewing/Entry")
async def viewing_create(request: Request):
    form = await request.form()
    cust = db.customers.get(form.get("CustomerId"))
    prop = db.properties.get(form.get("PropertyId"))
    agent = db.employees.get(form.get("EmployeeId"))
    vid = db.next_id("Viewing")
    db.viewings[vid] = {
        "Id": vid, "CustomerId": cust["Id"] if cust else "", "CustomerName": cust["Name"] if cust else "不明",
        "PropertyId": prop["Id"] if prop else "", "PropertyName": prop["Name"] if prop else "不明",
        "EmployeeId": agent["Id"] if agent else "", "EmployeeName": agent["Name"] if agent else "未定",
        "ViewingDate": form.get("ViewingDate", ""), "Status": form.get("Status") or "予約",
        "Feedback": form.get("Feedback", ""), "CreatedAt": form.get("ViewingDate", ""),
    }
    return redirect_to(request, "/Viewing/List")


@app.post("/Viewing/Entry/{vid}")
async def viewing_update(request: Request, vid: str):
    form = await request.form()
    v = db.viewings.get(vid)
    if not v:
        return redirect_to(request, "/Viewing/List")
    cust = db.customers.get(form.get("CustomerId"))
    prop = db.properties.get(form.get("PropertyId"))
    agent = db.employees.get(form.get("EmployeeId"))
    v.update({
        "CustomerId": cust["Id"] if cust else v["CustomerId"],
        "CustomerName": cust["Name"] if cust else v["CustomerName"],
        "PropertyId": prop["Id"] if prop else v["PropertyId"],
        "PropertyName": prop["Name"] if prop else v["PropertyName"],
        "EmployeeId": agent["Id"] if agent else v["EmployeeId"],
        "EmployeeName": agent["Name"] if agent else v["EmployeeName"],
        "ViewingDate": form.get("ViewingDate", v["ViewingDate"]),
        "Status": form.get("Status", v["Status"]),
        "Feedback": form.get("Feedback", v["Feedback"]),
    })
    db.viewings[vid] = v  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    return redirect_to(request, "/Viewing/List")


@app.get("/Viewing/Detail/{vid}")
def viewing_detail(request: Request, vid: str):
    v = db.viewings.get(vid)
    if not v:
        return redirect_to(request, "/Viewing/List")
    fields = [
        field("CustomerName", "顧客名"), field("PropertyName", "物件"), field("EmployeeName", "担当エージェント"),
        field("ViewingDate", "内見日"), field("Status", "ステータス"), field("Feedback", "所見/フィードバック"),
    ]
    return render_detail(request, title="内見予約詳細", heading="内見予約詳細", entity_path="Viewing",
                          fields=fields, values=v, record_id=vid)


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
    uvicorn.run("main:app", host="0.0.0.0", port=5030, reload=True)
