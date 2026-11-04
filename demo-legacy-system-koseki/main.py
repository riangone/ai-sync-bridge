"""
デモ・レガシーシステム（自治体窓口版: 戸籍・住基, localhost:5040）
==================================================================
AI機能ゼロの模擬WebForms風・自治体戸籍住民課システム。全7業務エンティティ
（Resident(住民)/Household(世帯)/FamilyRegister(戸籍)/Employee(窓口職員)/
CertificateRequest(証明書交付申請)/VisitReception(来庁受付)/MoveHistory(異動履歴)）
に対応するサーバーサイドHTMLレンダリング（Jinja2）画面群。

demo-legacy-system（製造業ERP版）/ demo-legacy-system-dealer（自動車ディーラー版）/
demo-legacy-system-realestate（不動産仲介版）と全く同じ設計（render_list/
render_entry/render_detail の汎用ヘルパー、entry_items.html の明細行グリッド）を、
自治体窓口業務（戸籍・住民基本台帳）ドメインに適用したもの。「既存のレガシー
システムを一切変更せずにAI機能を付与する」という AI-Sync Bridge のコンセプトが、
金融・製造・不動産に続き行政窓口でも同じ仕組み（aisb_embed のミドルウェア注入 +
読み取り専用JSON API）で成立することを示す4つ目のデモ。

想定ユースケース（アーキテクト視点の設計メモ）:
  - 窓口職員が住民を検索する場面 → AI検索パネルで
    「北沢に住む山田さん」のような曖昧な自然文から住民レコードへ到達できる。
  - 紙の申請書（住民票交付申請書等）をOCRで読み取り、CertificateRequestの
    入力フォームへ自動反映 → 窓口の手入力・聞き取りコストを削減。
  - 来庁受付(VisitReception)の混雑状況を予測分析パネルで可視化 → 窓口配置の
    最適化に活用。
  - 本体（住基ネット・LGWAN・他自治体システムとの連携基盤）には一切触れず、
    窓口フロント業務だけをAIで底上げする「リプレイスまでの橋渡し」という
    ai-sync-bridgeの基本コンセプトをそのまま踏襲する。

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

app = FastAPI(title="Municipal Family Register / Resident Registration Legacy System (Demo)")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# サブパス経由公開(例: https://host/koseki/... 経由でCaddyがstrip_prefixする構成)対応。
# Caddy側がX-Forwarded-Prefixを付与した場合のみ、テンプレート内の絶対パスリンクに
# プレフィックスを補う。ヘッダーが無ければ従来通り""(=完全無改変の挙動)。
templates.env.globals["base_path"] = lambda request: request.headers.get("x-forwarded-prefix", "")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")


def redirect_to(request: Request, path: str, status_code: int = 303) -> RedirectResponse:
    """POST後リダイレクト用。X-Forwarded-Prefix配下でも遷移先を正しく維持する。
    GET側テンプレートの base_path(request) と同じロジック(ヘッダー未設定時は""=無改変)。"""
    prefix = request.headers.get("x-forwarded-prefix", "")
    return RedirectResponse(f"{prefix}{path}", status_code=status_code)


aisb_embed.mount(app, profile_dir=Path(__file__).parent / "aisb_profile")


# ---------------------------------------------------------------------------
# 共通ヘルパー（他demoと同一実装）
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
RESIDENT_FIELDS = [
    field("Name", "氏名", required=True),
    field("NameKana", "フリガナ"),
    field("Gender", "性別", "select", ["男", "女"]),
    field("BirthDate", "生年月日", "date"),
    field("Relationship", "続柄", "select", db.RELATIONSHIPS),
    field("HouseholdId", "世帯", "select"),  # options injected per-request
    field("Address", "住所"),
    field("Tel", "TEL"),
    field("MyNumber", "個人番号(マスク表示)"),
    field("Status", "住民票ステータス", "select", db.RESIDENT_STATUSES),
    field("MoveInDate", "転入日", "date"),
    field("Notes", "備考", "textarea"),
]
RESIDENT_LIST_COLUMNS = [
    ("Id", "住民番号"), ("Name", "氏名"), ("NameKana", "フリガナ"), ("Gender", "性別"),
    ("BirthDate", "生年月日"), ("Address", "住所"), ("Status", "ステータス"),
]

HOUSEHOLD_FIELDS = [
    field("Address", "住所", required=True),
    field("Notes", "備考", "textarea"),
]
HOUSEHOLD_LIST_COLUMNS = [
    ("Id", "世帯番号"), ("HeadName", "世帯主"), ("Address", "住所"), ("MemberCount", "世帯人数"),
]

FAMILY_REGISTER_FIELDS = [
    field("HeadName", "筆頭者氏名", required=True),
    field("HonName", "本籍"),
    field("RegisterType", "戸籍種別", "select", db.FAMILY_REGISTER_TYPES),
    field("MemberCount", "在籍人数", "number"),
    field("CompiledDate", "編製日", "date"),
    field("Notes", "備考", "textarea"),
]
FAMILY_REGISTER_LIST_COLUMNS = [
    ("Id", "戸籍番号"), ("HeadName", "筆頭者"), ("HonName", "本籍"),
    ("RegisterType", "戸籍種別"), ("CompiledDate", "編製日"),
]

EMPLOYEE_FIELDS = [
    field("Name", "氏名", required=True),
    field("Department", "所属", "select", db.DEPARTMENTS),
    field("Position", "職位", "select", db.POSITIONS),
    field("CounterNo", "担当窓口"),
    field("Email", "メール"),
    field("Tel", "TEL"),
    field("HireDate", "採用日", "date"),
]
EMPLOYEE_LIST_COLUMNS = [
    ("Id", "職員番号"), ("Name", "氏名"), ("Department", "所属"), ("Position", "職位"),
    ("CounterNo", "担当窓口"), ("Tel", "TEL"),
]

VISIT_RECEPTION_FIELDS = [
    field("VisitorId", "来庁者(住民)", "select", required=True),
    field("Purpose", "用件", "select", db.VISIT_PURPOSES),
    field("ReceptionTime", "受付日", "date", required=True),
    field("EmployeeId", "担当職員", "select"),
    field("Status", "呼出状況", "select", db.VISIT_STATUSES),
    field("Notes", "備考", "textarea"),
]
VISIT_RECEPTION_LIST_COLUMNS = [
    ("Id", "受付番号"), ("VisitorName", "来庁者"), ("Purpose", "用件"),
    ("ReceptionTime", "受付日"), ("CounterNo", "窓口"), ("Status", "呼出状況"),
]

CERT_REQUEST_LIST_COLUMNS = [
    ("Id", "申請番号"), ("CustomerName", "申請者"), ("OrderDate", "申請日"),
    ("Purpose", "用途"), ("TotalAmount", "手数料合計"), ("Status", "ステータス"),
]
MOVE_HISTORY_LIST_COLUMNS = [
    ("ProductName", "住民"), ("Type", "異動種別"), ("Date", "異動日"), ("Notes", "備考"),
]


def household_options():
    return [(h["Id"], f'{h["Id"]}（{h["HeadName"] or "世帯主未定"} / {h["Address"]}）') for h in db.households.values()]


def resident_options():
    return db.resident_options()


def employee_options():
    return [(e["Id"], e["Name"]) for e in db.employees.values()]


def certificate_type_list():
    return list(db.CERT_TYPES)


# ---------------------------------------------------------------------------
# JSON API（AI-Sync Bridge 連携用・読み取り専用。他demoと同一設計）
# ---------------------------------------------------------------------------
ENTITY_LABELS = {
    "Resident": "住民", "Household": "世帯", "FamilyRegister": "戸籍", "Employee": "窓口職員",
    "CertificateRequest": "証明書交付申請", "VisitReception": "来庁受付", "MoveHistory": "異動履歴",
}

_ENTITY_ROWS = {
    "Resident": lambda: list(db.residents.values()),
    "Household": lambda: list(db.households.values()),
    "FamilyRegister": lambda: list(db.family_registers.values()),
    "Employee": lambda: list(db.employees.values()),
    "CertificateRequest": lambda: list(db.certificate_requests.values()),
    "VisitReception": lambda: list(db.visit_receptions.values()),
    "MoveHistory": lambda: list(db.move_history),
}

_ENTITY_STORE = {
    "Resident": db.residents, "Household": db.households, "FamilyRegister": db.family_registers,
    "Employee": db.employees, "CertificateRequest": db.certificate_requests,
    "VisitReception": db.visit_receptions,
}

_ENTITY_ITEMS = {
    "CertificateRequest": db.certificate_request_items,
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
        "residents": len(db.residents),
        "households": len(db.households),
        "cert_requests": len(db.certificate_requests),
        "fee_total": sum(c["TotalAmount"] for c in db.certificate_requests.values()),
    }
    return templates.TemplateResponse(request, "index.html", {"title": "メインメニュー", "summary": summary})


@app.get("/ai-panel")
def ai_panel_intro(request: Request):
    return templates.TemplateResponse(request, "ai_intro.html", {"title": "AIサイドパネルのご案内"})


# ---------------------------------------------------------------------------
# Resident（住民/住基）
# ---------------------------------------------------------------------------
def resident_fields_with_options():
    fields = [dict(f) for f in RESIDENT_FIELDS]
    for f in fields:
        if f["name"] == "HouseholdId":
            f["options"] = [h["Id"] for h in db.households.values()]
    return fields


@app.get("/Resident/List")
def resident_list(request: Request):
    return render_list(request, title="住民一覧", heading="住民一覧（住民基本台帳）", entity_path="Resident",
                        columns=RESIDENT_LIST_COLUMNS, rows=list(db.residents.values()), show_search=True,
                        new_label="住民新規登録")


@app.get("/Resident/Entry")
def resident_entry_new(request: Request):
    return render_entry(request, title="住民新規登録", heading="住民新規登録", entity_path="Resident",
                         fields=resident_fields_with_options(), values={}, is_edit=False)


@app.get("/Resident/Entry/{rid}")
def resident_entry_edit(request: Request, rid: str):
    r = db.residents.get(rid)
    if not r:
        return redirect_to(request, "/Resident/List")
    return render_entry(request, title="住民編集", heading="住民編集", entity_path="Resident",
                         fields=resident_fields_with_options(), values=r, is_edit=True, record_id=rid)


@app.post("/Resident/Entry")
async def resident_create(request: Request):
    form = await request.form()
    values = form_values(form, RESIDENT_FIELDS)
    rid = db.next_id("Resident")
    values.update({"Id": rid, "MyNumber": db._my_number_masked(), "CreatedAt": db._rand_date(0, 0)})
    db.residents[rid] = values
    return redirect_to(request, "/Resident/List")


@app.post("/Resident/Entry/{rid}")
async def resident_update(request: Request, rid: str):
    form = await request.form()
    values = form_values(form, RESIDENT_FIELDS)
    existing = db.residents.get(rid, {})
    existing.update(values)
    existing["Id"] = rid
    db.residents[rid] = existing
    return redirect_to(request, "/Resident/List")


@app.get("/Resident/Detail/{rid}")
def resident_detail(request: Request, rid: str):
    r = db.residents.get(rid)
    if not r:
        return redirect_to(request, "/Resident/List")
    return render_detail(request, title="住民詳細", heading="住民詳細", entity_path="Resident",
                          fields=RESIDENT_FIELDS, values=r, record_id=rid)


@app.get("/Resident/Search")
def resident_search_form(request: Request):
    return templates.TemplateResponse(request, "resident_search.html",
                                       {"title": "住民検索", "keyword": None, "results": None})


@app.post("/Resident/Search")
async def resident_search_submit(request: Request):
    form = await request.form()
    keyword = (form.get("keyword") or "").strip()
    results = list(db.residents.values())
    if keyword:
        results = [r for r in results if keyword in r["Name"] or keyword in (r["NameKana"] or "")
                   or keyword in (r["Address"] or "")]
    return templates.TemplateResponse(request, "resident_search.html",
                                       {"title": "住民検索", "keyword": keyword, "results": results})


# ---------------------------------------------------------------------------
# Household（世帯）
# ---------------------------------------------------------------------------
@app.get("/Household/List")
def household_list(request: Request):
    return render_list(request, title="世帯一覧", heading="世帯一覧", entity_path="Household",
                        columns=HOUSEHOLD_LIST_COLUMNS, rows=list(db.households.values()),
                        new_label="世帯新規登録")


@app.get("/Household/Entry")
def household_entry_new(request: Request):
    return render_entry(request, title="世帯新規登録", heading="世帯新規登録", entity_path="Household",
                         fields=HOUSEHOLD_FIELDS, values={}, is_edit=False)


@app.get("/Household/Entry/{hid}")
def household_entry_edit(request: Request, hid: str):
    h = db.households.get(hid)
    if not h:
        return redirect_to(request, "/Household/List")
    return render_entry(request, title="世帯編集", heading="世帯編集", entity_path="Household",
                         fields=HOUSEHOLD_FIELDS, values=h, is_edit=True, record_id=hid)


@app.post("/Household/Entry")
async def household_create(request: Request):
    form = await request.form()
    values = form_values(form, HOUSEHOLD_FIELDS)
    hid = db.next_id("Household")
    values.update({"Id": hid, "HeadName": "", "MemberCount": 0, "CreatedAt": db._rand_date(0, 0)})
    db.households[hid] = values
    return redirect_to(request, "/Household/List")


@app.post("/Household/Entry/{hid}")
async def household_update(request: Request, hid: str):
    form = await request.form()
    values = form_values(form, HOUSEHOLD_FIELDS)
    existing = db.households.get(hid, {})
    existing.update(values)
    existing["Id"] = hid
    db.households[hid] = existing
    return redirect_to(request, "/Household/List")


@app.get("/Household/Detail/{hid}")
def household_detail(request: Request, hid: str):
    h = db.households.get(hid)
    if not h:
        return redirect_to(request, "/Household/List")
    fields = [
        field("HeadName", "世帯主"), field("Address", "住所"), field("MemberCount", "世帯人数", "number"),
        field("Notes", "備考"),
    ]
    return render_detail(request, title="世帯詳細", heading="世帯詳細", entity_path="Household",
                          fields=fields, values=h, record_id=hid)


# ---------------------------------------------------------------------------
# FamilyRegister（戸籍）
# ---------------------------------------------------------------------------
@app.get("/FamilyRegister/List")
def family_register_list(request: Request):
    return render_list(request, title="戸籍一覧", heading="戸籍一覧", entity_path="FamilyRegister",
                        columns=FAMILY_REGISTER_LIST_COLUMNS, rows=list(db.family_registers.values()),
                        new_label="戸籍新規編製")


@app.get("/FamilyRegister/Entry")
def family_register_entry_new(request: Request):
    return render_entry(request, title="戸籍新規編製", heading="戸籍新規編製", entity_path="FamilyRegister",
                         fields=FAMILY_REGISTER_FIELDS, values={}, is_edit=False)


@app.get("/FamilyRegister/Entry/{fid}")
def family_register_entry_edit(request: Request, fid: str):
    f = db.family_registers.get(fid)
    if not f:
        return redirect_to(request, "/FamilyRegister/List")
    return render_entry(request, title="戸籍編集", heading="戸籍編集", entity_path="FamilyRegister",
                         fields=FAMILY_REGISTER_FIELDS, values=f, is_edit=True, record_id=fid)


@app.post("/FamilyRegister/Entry")
async def family_register_create(request: Request):
    form = await request.form()
    values = form_values(form, FAMILY_REGISTER_FIELDS)
    fid = db.next_id("FamilyRegister")
    values.update({"Id": fid, "CreatedAt": db._rand_date(0, 0)})
    db.family_registers[fid] = values
    return redirect_to(request, "/FamilyRegister/List")


@app.post("/FamilyRegister/Entry/{fid}")
async def family_register_update(request: Request, fid: str):
    form = await request.form()
    values = form_values(form, FAMILY_REGISTER_FIELDS)
    existing = db.family_registers.get(fid, {})
    existing.update(values)
    existing["Id"] = fid
    db.family_registers[fid] = existing
    return redirect_to(request, "/FamilyRegister/List")


@app.get("/FamilyRegister/Detail/{fid}")
def family_register_detail(request: Request, fid: str):
    f = db.family_registers.get(fid)
    if not f:
        return redirect_to(request, "/FamilyRegister/List")
    return render_detail(request, title="戸籍詳細", heading="戸籍詳細", entity_path="FamilyRegister",
                          fields=FAMILY_REGISTER_FIELDS, values=f, record_id=fid)


# ---------------------------------------------------------------------------
# Employee（窓口職員）
# ---------------------------------------------------------------------------
@app.get("/Employee/List")
def employee_list(request: Request):
    return render_list(request, title="窓口職員一覧", heading="窓口職員一覧", entity_path="Employee",
                        columns=EMPLOYEE_LIST_COLUMNS, rows=list(db.employees.values()),
                        new_label="職員新規登録")


@app.get("/Employee/Entry")
def employee_entry_new(request: Request):
    return render_entry(request, title="職員新規登録", heading="職員新規登録", entity_path="Employee",
                         fields=EMPLOYEE_FIELDS, values={}, is_edit=False)


@app.get("/Employee/Entry/{eid}")
def employee_entry_edit(request: Request, eid: str):
    e = db.employees.get(eid)
    if not e:
        return redirect_to(request, "/Employee/List")
    return render_entry(request, title="職員編集", heading="職員編集", entity_path="Employee",
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
    return render_detail(request, title="職員詳細", heading="職員詳細", entity_path="Employee",
                          fields=EMPLOYEE_FIELDS, values=e, record_id=eid)


# ---------------------------------------------------------------------------
# CertificateRequest（証明書交付申請） — 明細行グリッド付き（最重要画面）
# 明細行の対象は証明書種別(CERT_TYPES)。1申請で複数種別・複数通を交付可能。
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


@app.get("/CertificateRequest/List")
def cert_request_list(request: Request):
    return render_list(request, title="証明書交付申請一覧", heading="証明書交付申請一覧", entity_path="CertificateRequest",
                        columns=CERT_REQUEST_LIST_COLUMNS, rows=list(db.certificate_requests.values()),
                        new_label="証明書交付申請登録", money_fields={"TotalAmount"})


@app.get("/CertificateRequest/Entry")
def cert_request_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "証明書交付申請入力", "heading": "証明書交付申請入力", "entity_path": "CertificateRequest",
        "partner_label": "申請者(住民)", "partner_field": "customerId", "partner_options": resident_options(),
        "date1_label": "申請日", "date1_name": "orderDate", "date2_label": "交付予定日", "date2_name": "deliveryDate",
        "products": certificate_type_list(), "items": [], "values": {}, "is_edit": False,
        "total_elem_id": "certificaterequest-total",
    })


@app.get("/CertificateRequest/Entry/{cid}")
def cert_request_entry_edit(request: Request, cid: str):
    c = db.certificate_requests.get(cid)
    if not c:
        return redirect_to(request, "/CertificateRequest/List")
    values = dict(c)
    values["customerId"] = c["CustomerId"]
    values["orderDate"] = c["OrderDate"]
    values["deliveryDate"] = c["DeliveryDate"]
    values["_total"] = c["TotalAmount"]
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "証明書交付申請編集", "heading": "証明書交付申請編集", "entity_path": "CertificateRequest",
        "partner_label": "申請者(住民)", "partner_field": "customerId", "partner_options": resident_options(),
        "date1_label": "申請日", "date1_name": "orderDate", "date2_label": "交付予定日", "date2_name": "deliveryDate",
        "products": certificate_type_list(), "items": db.certificate_request_items.get(cid, []), "values": values,
        "is_edit": True, "record_id": cid, "total_elem_id": "certificaterequest-total",
    })


@app.post("/CertificateRequest/Entry")
async def cert_request_create(request: Request):
    form = await request.form()
    applicant = db.residents.get(form.get("customerId"))
    items = parse_item_rows(form, db.certificate_catalog())
    total = sum(it["Amount"] for it in items)
    cid = db.next_id("CertificateRequest")
    req_date = form.get("orderDate", "")
    db.certificate_requests[cid] = {
        "Id": cid, "CustomerId": applicant["Id"] if applicant else "",
        "CustomerName": applicant["Name"] if applicant else "不明",
        "OrderDate": req_date, "DeliveryDate": form.get("deliveryDate", ""),
        "TotalAmount": total, "Status": "受付", "Purpose": "その他", "Notes": form.get("notes", ""),
        "CreatedAt": req_date,
    }
    db.certificate_request_items[cid] = items
    return redirect_to(request, "/CertificateRequest/List")


@app.post("/CertificateRequest/Entry/{cid}")
async def cert_request_update(request: Request, cid: str):
    form = await request.form()
    c = db.certificate_requests.get(cid)
    if not c:
        return redirect_to(request, "/CertificateRequest/List")
    applicant = db.residents.get(form.get("customerId"))
    items = parse_item_rows(form, db.certificate_catalog())
    total = sum(it["Amount"] for it in items)
    c.update({
        "CustomerId": applicant["Id"] if applicant else c["CustomerId"],
        "CustomerName": applicant["Name"] if applicant else c["CustomerName"],
        "OrderDate": form.get("orderDate", c["OrderDate"]),
        "DeliveryDate": form.get("deliveryDate", c["DeliveryDate"]),
        "TotalAmount": total, "Notes": form.get("notes", c["Notes"]),
    })
    db.certificate_requests[cid] = c  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    db.certificate_request_items[cid] = items
    return redirect_to(request, "/CertificateRequest/List")


@app.get("/CertificateRequest/Detail/{cid}")
def cert_request_detail(request: Request, cid: str):
    c = db.certificate_requests.get(cid)
    if not c:
        return redirect_to(request, "/CertificateRequest/List")
    fields = [
        field("CustomerName", "申請者"), field("OrderDate", "申請日"), field("DeliveryDate", "交付予定日"),
        field("TotalAmount", "手数料合計", "number"), field("Purpose", "用途"),
        field("Status", "ステータス"), field("Notes", "備考"),
    ]
    return render_detail(request, title="証明書交付申請詳細", heading="証明書交付申請詳細", entity_path="CertificateRequest",
                          fields=fields, values=c, record_id=cid, items=db.certificate_request_items.get(cid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# VisitReception（来庁受付/整理券） — 自治体窓口特有の新設エンティティ
# ---------------------------------------------------------------------------
def visit_reception_fields_with_options():
    fields = [dict(f) for f in VISIT_RECEPTION_FIELDS]
    for f in fields:
        if f["name"] == "VisitorId":
            f["options"] = [r["Id"] for r in db.residents.values()]
        if f["name"] == "EmployeeId":
            f["options"] = [""] + [e["Id"] for e in db.employees.values()]
    return fields


@app.get("/VisitReception/List")
def visit_reception_list(request: Request):
    return render_list(request, title="来庁受付一覧", heading="来庁受付一覧（整理券）", entity_path="VisitReception",
                        columns=VISIT_RECEPTION_LIST_COLUMNS, rows=list(db.visit_receptions.values()),
                        new_label="来庁受付登録")


@app.get("/VisitReception/Entry")
def visit_reception_entry_new(request: Request):
    return render_entry(request, title="来庁受付登録", heading="来庁受付登録", entity_path="VisitReception",
                         fields=visit_reception_fields_with_options(), values={}, is_edit=False)


@app.get("/VisitReception/Entry/{vid}")
def visit_reception_entry_edit(request: Request, vid: str):
    v = db.visit_receptions.get(vid)
    if not v:
        return redirect_to(request, "/VisitReception/List")
    values = dict(v)
    values["VisitorId"] = v["VisitorId"]
    return render_entry(request, title="来庁受付編集", heading="来庁受付編集", entity_path="VisitReception",
                         fields=visit_reception_fields_with_options(), values=values, is_edit=True, record_id=vid)


@app.post("/VisitReception/Entry")
async def visit_reception_create(request: Request):
    form = await request.form()
    visitor = db.residents.get(form.get("VisitorId"))
    staff = db.employees.get(form.get("EmployeeId"))
    vid = db.next_id("VisitReception")
    db.visit_receptions[vid] = {
        "Id": vid, "VisitorId": visitor["Id"] if visitor else "", "VisitorName": visitor["Name"] if visitor else "不明",
        "Purpose": form.get("Purpose") or "証明書交付", "ReceptionTime": form.get("ReceptionTime", ""),
        "CounterNo": staff["CounterNo"] if staff else "", "EmployeeId": staff["Id"] if staff else "",
        "EmployeeName": staff["Name"] if staff else "未割当", "Status": form.get("Status") or "待機中",
        "Notes": form.get("Notes", ""), "CreatedAt": form.get("ReceptionTime", ""),
    }
    return redirect_to(request, "/VisitReception/List")


@app.post("/VisitReception/Entry/{vid}")
async def visit_reception_update(request: Request, vid: str):
    form = await request.form()
    v = db.visit_receptions.get(vid)
    if not v:
        return redirect_to(request, "/VisitReception/List")
    visitor = db.residents.get(form.get("VisitorId"))
    staff = db.employees.get(form.get("EmployeeId"))
    v.update({
        "VisitorId": visitor["Id"] if visitor else v["VisitorId"],
        "VisitorName": visitor["Name"] if visitor else v["VisitorName"],
        "Purpose": form.get("Purpose", v["Purpose"]),
        "ReceptionTime": form.get("ReceptionTime", v["ReceptionTime"]),
        "CounterNo": staff["CounterNo"] if staff else v["CounterNo"],
        "EmployeeId": staff["Id"] if staff else v["EmployeeId"],
        "EmployeeName": staff["Name"] if staff else v["EmployeeName"],
        "Status": form.get("Status", v["Status"]),
        "Notes": form.get("Notes", v["Notes"]),
    })
    db.visit_receptions[vid] = v  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    return redirect_to(request, "/VisitReception/List")


@app.get("/VisitReception/Detail/{vid}")
def visit_reception_detail(request: Request, vid: str):
    v = db.visit_receptions.get(vid)
    if not v:
        return redirect_to(request, "/VisitReception/List")
    fields = [
        field("VisitorName", "来庁者"), field("Purpose", "用件"), field("ReceptionTime", "受付日"),
        field("CounterNo", "担当窓口"), field("EmployeeName", "担当職員"), field("Status", "呼出状況"),
        field("Notes", "備考"),
    ]
    return render_detail(request, title="来庁受付詳細", heading="来庁受付詳細", entity_path="VisitReception",
                          fields=fields, values=v, record_id=vid)


# ---------------------------------------------------------------------------
# MoveHistory（異動履歴） — 一覧のみ。元ERPのInventoryTransactionに相当し、
# 住民票上の転入/転出/転居/婚姻/出生/死亡等の異動記録を保持する。
# ---------------------------------------------------------------------------
@app.get("/MoveHistory/List")
def move_history_list(request: Request):
    rows = sorted(db.move_history, key=lambda r: r["Date"], reverse=True)
    return render_list(request, title="異動履歴", heading="異動履歴", entity_path="MoveHistory",
                        columns=MOVE_HISTORY_LIST_COLUMNS, rows=rows, show_entry=False, show_detail=False)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5040, reload=True)
