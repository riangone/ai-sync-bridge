"""
デモ・レガシーシステム（年金照会端末版: 日本年金機構コールセンター/窓口, localhost:5050）
==================================================================
AI機能ゼロの模擬WebForms風・年金相談業務システム。全7業務エンティティ
（Insured(被保険者)/Employer(適用事業所)/EnrollmentRecord(適用記録)/Staff(相談員)/
PensionClaimRequest(年金請求/裁定請求受付)/CallReception(来所・電話相談受付)/
ContributionHistory(資格異動履歴)）に対応するサーバーサイドHTMLレンダリング
（Jinja2）画面群。

demo-legacy-system（製造業ERP版）/ demo-legacy-system-dealer（自動車ディーラー版）/
demo-legacy-system-realestate（不動産仲介版）/ demo-legacy-system-koseki（自治体窓口版）
と全く同じ設計（render_list/render_entry/render_detail の汎用ヘルパー、
entry_items.html の明細行グリッド）を、年金相談業務（日本年金機構コールセンター/
年金事務所窓口の照会端末）ドメインに適用したもの。「既存のレガシーシステムを
一切変更せずにAI機能を付与する」という AI-Sync Bridge のコンセプトが、金融・
製造・不動産・行政窓口に続き年金相談窓口でも同じ仕組み（aisb_embed のミドルウェア
注入 + 読み取り専用JSON API）で成立することを示す5つ目のデモ。

想定ユースケース（アーキテクト視点の設計メモ）:
  - コールセンターのオペレーター/年金事務所窓口の相談員が被保険者を検索する場面
    → AI検索パネルで「〇〇さんの加入記録」のような曖昧な
    自然文から被保険者レコードへ到達できる。
  - 紙の裁定請求書をOCRで読み取り、PensionClaimRequestの入力フォームへ自動反映
    → 窓口の手入力・聞き取りコストを削減。
  - 来所・電話相談受付(CallReception)の混雑状況を予測分析パネルで可視化 →
    窓口/オペレーター配置の最適化に活用。
  - 本体（社会保険オンラインシステム・基礎年金番号管理システム等の基幹系）には
    一切触れず、相談窓口フロント業務だけをAIで底上げする「リプレイスまでの
    橋渡し」という ai-sync-bridge の基本コンセプトをそのまま踏襲する。

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

app = FastAPI(title="Pension Inquiry Terminal Legacy System (Demo)")
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
# サブパス経由公開(例: https://host/nenkin/... 経由でCaddyがstrip_prefixする構成)対応。
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
INSURED_FIELDS = [
    field("Name", "氏名", required=True),
    field("NameKana", "フリガナ"),
    field("Gender", "性別", "select", ["男", "女"]),
    field("BirthDate", "生年月日", "date"),
    field("InsuredType", "被保険者種別", "select", db.INSURED_TYPES),
    field("EmployerId", "適用事業所", "select"),  # options injected per-request
    field("Address", "住所"),
    field("Tel", "TEL"),
    field("BasicPensionNumber", "基礎年金番号(マスク表示)"),
    field("Status", "資格状況", "select", db.INSURED_STATUSES),
    field("AcquisitionDate", "資格取得日", "date"),
    field("Notes", "備考", "textarea"),
]
INSURED_LIST_COLUMNS = [
    ("Id", "被保険者番号"), ("Name", "氏名"), ("NameKana", "フリガナ"), ("Gender", "性別"),
    ("BirthDate", "生年月日"), ("Address", "住所"), ("Status", "資格状況"),
]

EMPLOYER_FIELDS = [
    field("Name", "事業所名称", required=True),
    field("Address", "所在地", required=True),
    field("Industry", "業種", "select", db.INDUSTRIES),
    field("Notes", "備考", "textarea"),
]
EMPLOYER_LIST_COLUMNS = [
    ("Id", "事業所番号"), ("Name", "事業所名称"), ("Address", "所在地"),
    ("Industry", "業種"), ("MemberCount", "加入者数"),
]

ENROLLMENT_RECORD_FIELDS = [
    field("EmployerName", "事業所名称", required=True),
    field("PensionOffice", "管轄年金事務所"),
    field("PensionType", "制度種別", "select", db.PENSION_TYPES),
    field("InsuredCount", "加入被保険者数", "number"),
    field("ApplicationDate", "適用開始日", "date"),
    field("Notes", "備考", "textarea"),
]
ENROLLMENT_RECORD_LIST_COLUMNS = [
    ("Id", "記録番号"), ("EmployerName", "事業所名称"), ("PensionOffice", "管轄年金事務所"),
    ("PensionType", "制度種別"), ("ApplicationDate", "適用開始日"),
]

STAFF_FIELDS = [
    field("Name", "氏名", required=True),
    field("Department", "所属", "select", db.DEPARTMENTS),
    field("Position", "職位", "select", db.POSITIONS),
    field("CounterNo", "担当窓口/内線"),
    field("Email", "メール"),
    field("Tel", "TEL"),
    field("HireDate", "採用日", "date"),
]
STAFF_LIST_COLUMNS = [
    ("Id", "職員番号"), ("Name", "氏名"), ("Department", "所属"), ("Position", "職位"),
    ("CounterNo", "担当窓口/内線"), ("Tel", "TEL"),
]

CALL_RECEPTION_FIELDS = [
    field("VisitorId", "相談者(被保険者)", "select", required=True),
    field("Channel", "チャネル", "select", db.RECEPTION_CHANNELS),
    field("Purpose", "相談内容", "select", db.RECEPTION_PURPOSES),
    field("ReceptionTime", "受付日", "date", required=True),
    field("EmployeeId", "担当職員", "select"),
    field("Status", "対応状況", "select", db.RECEPTION_STATUSES),
    field("Notes", "備考", "textarea"),
]
CALL_RECEPTION_LIST_COLUMNS = [
    ("Id", "受付番号"), ("VisitorName", "相談者"), ("Channel", "チャネル"), ("Purpose", "相談内容"),
    ("ReceptionTime", "受付日"), ("Status", "対応状況"),
]

CLAIM_REQUEST_LIST_COLUMNS = [
    ("Id", "請求番号"), ("CustomerName", "請求者"), ("OrderDate", "受付日"),
    ("Purpose", "請求区分"), ("TotalAmount", "支給見込額合計(概算)"), ("Status", "審査状況"),
]
CONTRIBUTION_HISTORY_LIST_COLUMNS = [
    ("ProductName", "被保険者"), ("Type", "異動種別"), ("Date", "異動日"), ("Notes", "備考"),
]


def employer_options():
    return [(e["Id"], f'{e["Id"]}（{e["Name"]} / {e["Address"]}）') for e in db.employers.values()]


def insured_options():
    return db.insured_options()


def staff_options():
    return [(s["Id"], s["Name"]) for s in db.staff.values()]


def claim_type_list():
    return list(db.CLAIM_TYPES)


# ---------------------------------------------------------------------------
# JSON API（AI-Sync Bridge 連携用・読み取り専用。他demoと同一設計）
# ---------------------------------------------------------------------------
ENTITY_LABELS = {
    "Insured": "被保険者", "Employer": "適用事業所", "EnrollmentRecord": "適用記録", "Staff": "相談員",
    "PensionClaimRequest": "年金請求", "CallReception": "来所・電話相談受付", "ContributionHistory": "資格異動履歴",
}

_ENTITY_ROWS = {
    "Insured": lambda: list(db.insureds.values()),
    "Employer": lambda: list(db.employers.values()),
    "EnrollmentRecord": lambda: list(db.enrollment_records.values()),
    "Staff": lambda: list(db.staff.values()),
    "PensionClaimRequest": lambda: list(db.pension_claim_requests.values()),
    "CallReception": lambda: list(db.call_receptions.values()),
    "ContributionHistory": lambda: list(db.contribution_history),
}

_ENTITY_STORE = {
    "Insured": db.insureds, "Employer": db.employers, "EnrollmentRecord": db.enrollment_records,
    "Staff": db.staff, "PensionClaimRequest": db.pension_claim_requests,
    "CallReception": db.call_receptions,
}

_ENTITY_ITEMS = {
    "PensionClaimRequest": db.pension_claim_request_items,
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
        "insureds": len(db.insureds),
        "employers": len(db.employers),
        "claim_requests": len(db.pension_claim_requests),
        "fee_total": sum(c["TotalAmount"] for c in db.pension_claim_requests.values()),
    }
    return templates.TemplateResponse(request, "index.html", {"title": "メインメニュー", "summary": summary})


@app.get("/ai-panel")
def ai_panel_intro(request: Request):
    return templates.TemplateResponse(request, "ai_intro.html", {"title": "AIサイドパネルのご案内"})


# ---------------------------------------------------------------------------
# Insured（被保険者）
# ---------------------------------------------------------------------------
def insured_fields_with_options():
    fields = [dict(f) for f in INSURED_FIELDS]
    for f in fields:
        if f["name"] == "EmployerId":
            f["options"] = [""] + [e["Id"] for e in db.employers.values()]
    return fields


@app.get("/Insured/List")
def insured_list(request: Request):
    return render_list(request, title="被保険者一覧", heading="被保険者一覧（基礎年金番号管理）", entity_path="Insured",
                        columns=INSURED_LIST_COLUMNS, rows=list(db.insureds.values()), show_search=True,
                        new_label="被保険者新規登録")


@app.get("/Insured/Entry")
def insured_entry_new(request: Request):
    return render_entry(request, title="被保険者新規登録", heading="被保険者新規登録", entity_path="Insured",
                         fields=insured_fields_with_options(), values={}, is_edit=False)


@app.get("/Insured/Entry/{iid}")
def insured_entry_edit(request: Request, iid: str):
    p = db.insureds.get(iid)
    if not p:
        return redirect_to(request, "/Insured/List")
    return render_entry(request, title="被保険者編集", heading="被保険者編集", entity_path="Insured",
                         fields=insured_fields_with_options(), values=p, is_edit=True, record_id=iid)


@app.post("/Insured/Entry")
async def insured_create(request: Request):
    form = await request.form()
    values = form_values(form, INSURED_FIELDS)
    iid = db.next_id("Insured")
    values.update({"Id": iid, "BasicPensionNumber": db._basic_pension_number_masked(), "CreatedAt": db._rand_date(0, 0)})
    db.insureds[iid] = values
    return redirect_to(request, "/Insured/List")


@app.post("/Insured/Entry/{iid}")
async def insured_update(request: Request, iid: str):
    form = await request.form()
    values = form_values(form, INSURED_FIELDS)
    existing = db.insureds.get(iid, {})
    existing.update(values)
    existing["Id"] = iid
    db.insureds[iid] = existing
    return redirect_to(request, "/Insured/List")


@app.get("/Insured/Detail/{iid}")
def insured_detail(request: Request, iid: str):
    p = db.insureds.get(iid)
    if not p:
        return redirect_to(request, "/Insured/List")
    return render_detail(request, title="被保険者詳細", heading="被保険者詳細", entity_path="Insured",
                          fields=INSURED_FIELDS, values=p, record_id=iid)


@app.get("/Insured/Search")
def insured_search_form(request: Request):
    return templates.TemplateResponse(request, "insured_search.html",
                                       {"title": "被保険者検索", "keyword": None, "results": None})


@app.post("/Insured/Search")
async def insured_search_submit(request: Request):
    form = await request.form()
    keyword = (form.get("keyword") or "").strip()
    results = list(db.insureds.values())
    if keyword:
        results = [p for p in results if keyword in p["Name"] or keyword in (p["NameKana"] or "")
                   or keyword in (p["Address"] or "")]
    return templates.TemplateResponse(request, "insured_search.html",
                                       {"title": "被保険者検索", "keyword": keyword, "results": results})


# ---------------------------------------------------------------------------
# Employer（適用事業所）
# ---------------------------------------------------------------------------
@app.get("/Employer/List")
def employer_list(request: Request):
    return render_list(request, title="適用事業所一覧", heading="適用事業所一覧", entity_path="Employer",
                        columns=EMPLOYER_LIST_COLUMNS, rows=list(db.employers.values()),
                        new_label="適用事業所新規登録")


@app.get("/Employer/Entry")
def employer_entry_new(request: Request):
    return render_entry(request, title="適用事業所新規登録", heading="適用事業所新規登録", entity_path="Employer",
                         fields=EMPLOYER_FIELDS, values={}, is_edit=False)


@app.get("/Employer/Entry/{eid}")
def employer_entry_edit(request: Request, eid: str):
    e = db.employers.get(eid)
    if not e:
        return redirect_to(request, "/Employer/List")
    return render_entry(request, title="適用事業所編集", heading="適用事業所編集", entity_path="Employer",
                         fields=EMPLOYER_FIELDS, values=e, is_edit=True, record_id=eid)


@app.post("/Employer/Entry")
async def employer_create(request: Request):
    form = await request.form()
    values = form_values(form, EMPLOYER_FIELDS)
    eid = db.next_id("Employer")
    values.update({"Id": eid, "MemberCount": 0, "CreatedAt": db._rand_date(0, 0)})
    db.employers[eid] = values
    return redirect_to(request, "/Employer/List")


@app.post("/Employer/Entry/{eid}")
async def employer_update(request: Request, eid: str):
    form = await request.form()
    values = form_values(form, EMPLOYER_FIELDS)
    existing = db.employers.get(eid, {})
    existing.update(values)
    existing["Id"] = eid
    db.employers[eid] = existing
    return redirect_to(request, "/Employer/List")


@app.get("/Employer/Detail/{eid}")
def employer_detail(request: Request, eid: str):
    e = db.employers.get(eid)
    if not e:
        return redirect_to(request, "/Employer/List")
    fields = [
        field("Name", "事業所名称"), field("Address", "所在地"), field("Industry", "業種"),
        field("MemberCount", "加入者数", "number"), field("Notes", "備考"),
    ]
    return render_detail(request, title="適用事業所詳細", heading="適用事業所詳細", entity_path="Employer",
                          fields=fields, values=e, record_id=eid)


# ---------------------------------------------------------------------------
# EnrollmentRecord（適用事業所の厚生年金適用記録）
# ---------------------------------------------------------------------------
@app.get("/EnrollmentRecord/List")
def enrollment_record_list(request: Request):
    return render_list(request, title="適用記録一覧", heading="適用記録一覧", entity_path="EnrollmentRecord",
                        columns=ENROLLMENT_RECORD_LIST_COLUMNS, rows=list(db.enrollment_records.values()),
                        new_label="適用記録新規登録")


@app.get("/EnrollmentRecord/Entry")
def enrollment_record_entry_new(request: Request):
    return render_entry(request, title="適用記録新規登録", heading="適用記録新規登録", entity_path="EnrollmentRecord",
                         fields=ENROLLMENT_RECORD_FIELDS, values={}, is_edit=False)


@app.get("/EnrollmentRecord/Entry/{rid}")
def enrollment_record_entry_edit(request: Request, rid: str):
    r = db.enrollment_records.get(rid)
    if not r:
        return redirect_to(request, "/EnrollmentRecord/List")
    return render_entry(request, title="適用記録編集", heading="適用記録編集", entity_path="EnrollmentRecord",
                         fields=ENROLLMENT_RECORD_FIELDS, values=r, is_edit=True, record_id=rid)


@app.post("/EnrollmentRecord/Entry")
async def enrollment_record_create(request: Request):
    form = await request.form()
    values = form_values(form, ENROLLMENT_RECORD_FIELDS)
    rid = db.next_id("EnrollmentRecord")
    values.update({"Id": rid, "CreatedAt": db._rand_date(0, 0)})
    db.enrollment_records[rid] = values
    return redirect_to(request, "/EnrollmentRecord/List")


@app.post("/EnrollmentRecord/Entry/{rid}")
async def enrollment_record_update(request: Request, rid: str):
    form = await request.form()
    values = form_values(form, ENROLLMENT_RECORD_FIELDS)
    existing = db.enrollment_records.get(rid, {})
    existing.update(values)
    existing["Id"] = rid
    db.enrollment_records[rid] = existing
    return redirect_to(request, "/EnrollmentRecord/List")


@app.get("/EnrollmentRecord/Detail/{rid}")
def enrollment_record_detail(request: Request, rid: str):
    r = db.enrollment_records.get(rid)
    if not r:
        return redirect_to(request, "/EnrollmentRecord/List")
    return render_detail(request, title="適用記録詳細", heading="適用記録詳細", entity_path="EnrollmentRecord",
                          fields=ENROLLMENT_RECORD_FIELDS, values=r, record_id=rid)


# ---------------------------------------------------------------------------
# Staff（相談員/窓口職員）
# ---------------------------------------------------------------------------
@app.get("/Staff/List")
def staff_list(request: Request):
    return render_list(request, title="相談員一覧", heading="相談員一覧", entity_path="Staff",
                        columns=STAFF_LIST_COLUMNS, rows=list(db.staff.values()),
                        new_label="相談員新規登録")


@app.get("/Staff/Entry")
def staff_entry_new(request: Request):
    return render_entry(request, title="相談員新規登録", heading="相談員新規登録", entity_path="Staff",
                         fields=STAFF_FIELDS, values={}, is_edit=False)


@app.get("/Staff/Entry/{sid}")
def staff_entry_edit(request: Request, sid: str):
    s = db.staff.get(sid)
    if not s:
        return redirect_to(request, "/Staff/List")
    return render_entry(request, title="相談員編集", heading="相談員編集", entity_path="Staff",
                         fields=STAFF_FIELDS, values=s, is_edit=True, record_id=sid)


@app.post("/Staff/Entry")
async def staff_create(request: Request):
    form = await request.form()
    values = form_values(form, STAFF_FIELDS)
    sid = db.next_id("Staff")
    values.update({"Id": sid, "CreatedAt": db._rand_date(0, 0)})
    db.staff[sid] = values
    return redirect_to(request, "/Staff/List")


@app.post("/Staff/Entry/{sid}")
async def staff_update(request: Request, sid: str):
    form = await request.form()
    values = form_values(form, STAFF_FIELDS)
    existing = db.staff.get(sid, {})
    existing.update(values)
    existing["Id"] = sid
    db.staff[sid] = existing
    return redirect_to(request, "/Staff/List")


@app.get("/Staff/Detail/{sid}")
def staff_detail(request: Request, sid: str):
    s = db.staff.get(sid)
    if not s:
        return redirect_to(request, "/Staff/List")
    return render_detail(request, title="相談員詳細", heading="相談員詳細", entity_path="Staff",
                          fields=STAFF_FIELDS, values=s, record_id=sid)


# ---------------------------------------------------------------------------
# PensionClaimRequest（年金請求/裁定請求受付） — 明細行グリッド付き（最重要画面）
# 明細行の対象は年金給付種別(CLAIM_TYPES)。1請求で複数給付種別を計上可能。
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


@app.get("/PensionClaimRequest/List")
def claim_request_list(request: Request):
    return render_list(request, title="年金請求一覧", heading="年金請求（裁定請求）一覧", entity_path="PensionClaimRequest",
                        columns=CLAIM_REQUEST_LIST_COLUMNS, rows=list(db.pension_claim_requests.values()),
                        new_label="年金請求登録", money_fields={"TotalAmount"})


@app.get("/PensionClaimRequest/Entry")
def claim_request_entry_new(request: Request):
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "年金請求入力", "heading": "年金請求（裁定請求）入力", "entity_path": "PensionClaimRequest",
        "partner_label": "請求者(被保険者)", "partner_field": "customerId", "partner_options": insured_options(),
        "date1_label": "受付日", "date1_name": "orderDate", "date2_label": "裁定結果通知予定日", "date2_name": "deliveryDate",
        "products": claim_type_list(), "items": [], "values": {}, "is_edit": False,
        "total_elem_id": "pensionclaimrequest-total",
    })


@app.get("/PensionClaimRequest/Entry/{cid}")
def claim_request_entry_edit(request: Request, cid: str):
    c = db.pension_claim_requests.get(cid)
    if not c:
        return redirect_to(request, "/PensionClaimRequest/List")
    values = dict(c)
    values["customerId"] = c["CustomerId"]
    values["orderDate"] = c["OrderDate"]
    values["deliveryDate"] = c["DeliveryDate"]
    values["_total"] = c["TotalAmount"]
    return templates.TemplateResponse(request, "entry_items.html", {
        "title": "年金請求編集", "heading": "年金請求（裁定請求）編集", "entity_path": "PensionClaimRequest",
        "partner_label": "請求者(被保険者)", "partner_field": "customerId", "partner_options": insured_options(),
        "date1_label": "受付日", "date1_name": "orderDate", "date2_label": "裁定結果通知予定日", "date2_name": "deliveryDate",
        "products": claim_type_list(), "items": db.pension_claim_request_items.get(cid, []), "values": values,
        "is_edit": True, "record_id": cid, "total_elem_id": "pensionclaimrequest-total",
    })


@app.post("/PensionClaimRequest/Entry")
async def claim_request_create(request: Request):
    form = await request.form()
    applicant = db.insureds.get(form.get("customerId"))
    items = parse_item_rows(form, db.claim_catalog())
    total = sum(it["Amount"] for it in items)
    cid = db.next_id("PensionClaimRequest")
    req_date = form.get("orderDate", "")
    db.pension_claim_requests[cid] = {
        "Id": cid, "CustomerId": applicant["Id"] if applicant else "",
        "CustomerName": applicant["Name"] if applicant else "不明",
        "OrderDate": req_date, "DeliveryDate": form.get("deliveryDate", ""),
        "TotalAmount": total, "Status": "受付", "Purpose": "老齢給付裁定請求", "Notes": form.get("notes", ""),
        "CreatedAt": req_date,
    }
    db.pension_claim_request_items[cid] = items
    return redirect_to(request, "/PensionClaimRequest/List")


@app.post("/PensionClaimRequest/Entry/{cid}")
async def claim_request_update(request: Request, cid: str):
    form = await request.form()
    c = db.pension_claim_requests.get(cid)
    if not c:
        return redirect_to(request, "/PensionClaimRequest/List")
    applicant = db.insureds.get(form.get("customerId"))
    items = parse_item_rows(form, db.claim_catalog())
    total = sum(it["Amount"] for it in items)
    c.update({
        "CustomerId": applicant["Id"] if applicant else c["CustomerId"],
        "CustomerName": applicant["Name"] if applicant else c["CustomerName"],
        "OrderDate": form.get("orderDate", c["OrderDate"]),
        "DeliveryDate": form.get("deliveryDate", c["DeliveryDate"]),
        "TotalAmount": total, "Notes": form.get("notes", c["Notes"]),
    })
    db.pension_claim_requests[cid] = c  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    db.pension_claim_request_items[cid] = items
    return redirect_to(request, "/PensionClaimRequest/List")


@app.get("/PensionClaimRequest/Detail/{cid}")
def claim_request_detail(request: Request, cid: str):
    c = db.pension_claim_requests.get(cid)
    if not c:
        return redirect_to(request, "/PensionClaimRequest/List")
    fields = [
        field("CustomerName", "請求者"), field("OrderDate", "受付日"), field("DeliveryDate", "裁定結果通知予定日"),
        field("TotalAmount", "支給見込額合計(概算)", "number"), field("Purpose", "請求区分"),
        field("Status", "審査状況"), field("Notes", "備考"),
    ]
    return render_detail(request, title="年金請求詳細", heading="年金請求（裁定請求）詳細", entity_path="PensionClaimRequest",
                          fields=fields, values=c, record_id=cid, items=db.pension_claim_request_items.get(cid, []),
                          money_fields={"TotalAmount"})


# ---------------------------------------------------------------------------
# CallReception（来所・電話相談受付） — 年金相談窓口特有の新設エンティティ
# ---------------------------------------------------------------------------
def call_reception_fields_with_options():
    fields = [dict(f) for f in CALL_RECEPTION_FIELDS]
    for f in fields:
        if f["name"] == "VisitorId":
            f["options"] = [p["Id"] for p in db.insureds.values()]
        if f["name"] == "EmployeeId":
            f["options"] = [""] + [s["Id"] for s in db.staff.values()]
    return fields


@app.get("/CallReception/List")
def call_reception_list(request: Request):
    return render_list(request, title="来所・電話相談受付一覧", heading="来所・電話相談受付一覧", entity_path="CallReception",
                        columns=CALL_RECEPTION_LIST_COLUMNS, rows=list(db.call_receptions.values()),
                        new_label="相談受付登録")


@app.get("/CallReception/Entry")
def call_reception_entry_new(request: Request):
    return render_entry(request, title="相談受付登録", heading="相談受付登録", entity_path="CallReception",
                         fields=call_reception_fields_with_options(), values={}, is_edit=False)


@app.get("/CallReception/Entry/{vid}")
def call_reception_entry_edit(request: Request, vid: str):
    v = db.call_receptions.get(vid)
    if not v:
        return redirect_to(request, "/CallReception/List")
    values = dict(v)
    values["VisitorId"] = v["VisitorId"]
    return render_entry(request, title="相談受付編集", heading="相談受付編集", entity_path="CallReception",
                         fields=call_reception_fields_with_options(), values=values, is_edit=True, record_id=vid)


@app.post("/CallReception/Entry")
async def call_reception_create(request: Request):
    form = await request.form()
    visitor = db.insureds.get(form.get("VisitorId"))
    counselor = db.staff.get(form.get("EmployeeId"))
    vid = db.next_id("CallReception")
    db.call_receptions[vid] = {
        "Id": vid, "VisitorId": visitor["Id"] if visitor else "", "VisitorName": visitor["Name"] if visitor else "不明",
        "Channel": form.get("Channel") or "窓口", "Purpose": form.get("Purpose") or "その他",
        "ReceptionTime": form.get("ReceptionTime", ""),
        "CounterNo": counselor["CounterNo"] if counselor else "", "EmployeeId": counselor["Id"] if counselor else "",
        "EmployeeName": counselor["Name"] if counselor else "未割当", "Status": form.get("Status") or "待機中",
        "Notes": form.get("Notes", ""), "CreatedAt": form.get("ReceptionTime", ""),
    }
    return redirect_to(request, "/CallReception/List")


@app.post("/CallReception/Entry/{vid}")
async def call_reception_update(request: Request, vid: str):
    form = await request.form()
    v = db.call_receptions.get(vid)
    if not v:
        return redirect_to(request, "/CallReception/List")
    visitor = db.insureds.get(form.get("VisitorId"))
    counselor = db.staff.get(form.get("EmployeeId"))
    v.update({
        "VisitorId": visitor["Id"] if visitor else v["VisitorId"],
        "VisitorName": visitor["Name"] if visitor else v["VisitorName"],
        "Channel": form.get("Channel", v["Channel"]),
        "Purpose": form.get("Purpose", v["Purpose"]),
        "ReceptionTime": form.get("ReceptionTime", v["ReceptionTime"]),
        "CounterNo": counselor["CounterNo"] if counselor else v["CounterNo"],
        "EmployeeId": counselor["Id"] if counselor else v["EmployeeId"],
        "EmployeeName": counselor["Name"] if counselor else v["EmployeeName"],
        "Status": form.get("Status", v["Status"]),
        "Notes": form.get("Notes", v["Notes"]),
    })
    db.call_receptions[vid] = v  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    return redirect_to(request, "/CallReception/List")


@app.get("/CallReception/Detail/{vid}")
def call_reception_detail(request: Request, vid: str):
    v = db.call_receptions.get(vid)
    if not v:
        return redirect_to(request, "/CallReception/List")
    fields = [
        field("VisitorName", "相談者"), field("Channel", "チャネル"), field("Purpose", "相談内容"),
        field("ReceptionTime", "受付日"), field("CounterNo", "担当窓口/内線"), field("EmployeeName", "担当職員"),
        field("Status", "対応状況"), field("Notes", "備考"),
    ]
    return render_detail(request, title="相談受付詳細", heading="来所・電話相談受付詳細", entity_path="CallReception",
                          fields=fields, values=v, record_id=vid)


# ---------------------------------------------------------------------------
# ContributionHistory（資格異動履歴） — 一覧のみ。元ERPのInventoryTransactionに相当し、
# 被保険者記録上の資格取得/喪失/種別変更/氏名変更/住所変更等の異動記録を保持する。
# ---------------------------------------------------------------------------
@app.get("/ContributionHistory/List")
def contribution_history_list(request: Request):
    rows = sorted(db.contribution_history, key=lambda r: r["Date"], reverse=True)
    return render_list(request, title="資格異動履歴", heading="資格異動履歴", entity_path="ContributionHistory",
                        columns=CONTRIBUTION_HISTORY_LIST_COLUMNS, rows=rows, show_entry=False, show_detail=False)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5050, reload=True)
