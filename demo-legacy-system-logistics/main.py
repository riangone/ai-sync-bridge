"""
Demo Legacy Logistics & Warehouse System (WMS/TMS) — Port 5030.

3つ目の業務システム。ERP(5010)の受注番号(ORD1015 …)と顧客コード(C0001 …)で疎結合し、
出荷・配送状況(Shipment)、倉庫在庫(Stock)、機密の運送契約(FreightContract)を自分の DB(logistics.db)に持つ。

A2A の信頼関係(各 Bridge の bridge.yaml で宣言):
  - ERP ⇄ 物流 は直接の Peer。ERP からの直接の依頼は Shipment と Stock まで見える。
  - CRM と物流は直接の信頼関係を持たない。CRM の依頼は ERP が中継したときだけ届き、
    物流はそれを縮退ロール(a2a_relay_view)で評価する → Shipment(配送状況)だけ見える。
  - FreightContract(運賃・秘密割引)は物流の契約担当だけ。どの Agent にも渡さない。

この画面プロセスは A2A キーを持たない。操作は物流 Bridge(5031)の公開デモ経路へ中継する。
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import sqlite3
import urllib.error
import urllib.request
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger("legacy-logistics")

DB_PATH = os.getenv("AISB_LOGI_DB_PATH", str(Path(__file__).resolve().parent / "logistics.db"))
LOGI_BRIDGE_URL = os.getenv("AISB_LOGI_BRIDGE_URL", "http://127.0.0.1:5031").rstrip("/")

# ERP の固定シード(demo-legacy-system/data.py)と突き合わせた値。ERP 側が変わったら合わせる:
#   ORD1015 = 山田商事 / 確認中 / 納期 2026-08-24、ORD1032 = 佐藤工業 / 確認中、ORD1025 = 高橋物産 / 出荷済
SEED_SHIPMENTS = [
    {
        "Id": "SHP-L-1015", "OrderId": "ORD1015", "CustomerId": "C0001", "CustomerName": "山田商事",
        "Carrier": "西濃運輸", "Status": "出荷保留", "ShipDate": "", "ETA": "2026-12-03",
        "Destination": "山田商事 本社工場(大阪府東大阪市)",
        "DelayReason": "同梱部材「軸受ユニット E-104」の仕入先入荷遅延(11/20予定→11/28)。代替ロットを手配済みで 11/29 出荷予定。",
    },
    {
        "Id": "SHP-L-1032", "OrderId": "ORD1032", "CustomerId": "C0002", "CustomerName": "佐藤工業",
        "Carrier": "ヤマト運輸", "Status": "ピッキング中", "ShipDate": "2026-11-27", "ETA": "2026-11-29",
        "Destination": "佐藤工業 名古屋第二工場", "DelayReason": "",
    },
    {
        "Id": "SHP-L-1025", "OrderId": "ORD1025", "CustomerId": "C0004", "CustomerName": "高橋物産",
        "Carrier": "西濃運輸", "Status": "配達完了", "ShipDate": "2026-08-23", "ETA": "2026-08-25",
        "Destination": "高橋物産 東日本物流センター", "DelayReason": "",
    },
]

SEED_STOCKS = [
    {
        "Id": "STK-001", "ProductId": "P004", "ProductName": "軸受ユニット E-104", "Warehouse": "厚木第2倉庫",
        "Location": "A-12-03", "OnHand": 12, "Allocated": 12, "AllocatedOrderId": "ORD1015",
        "NextInbound": "2026-11-28 (+40)",
    },
    {
        "Id": "STK-002", "ProductId": "P001", "ProductName": "産業用ポンプ B-101", "Warehouse": "厚木第1倉庫",
        "Location": "B-03-01", "OnHand": 299, "Allocated": 20, "AllocatedOrderId": "ORD1032",
        "NextInbound": "",
    },
    {
        "Id": "STK-003", "ProductId": "P002", "ProductName": "制御盤 C-102", "Warehouse": "大阪倉庫",
        "Location": "C-07-02", "OnHand": 29, "Allocated": 0, "AllocatedOrderId": "",
        "NextInbound": "2026-12-05 (+10)",
    },
]

# 機密: 物流の契約担当(logi_contract)だけ。ERP / CRM の Agent からは絶対に見えない
SEED_FREIGHT = [
    {
        "Id": "FRT-2026-001", "Carrier": "西濃運輸", "ConfidentialLevel": "CONFIDENTIAL",
        "BaseRate": "1ケース ¥1,850(関西向け)", "CustomerSurcharge": "山田商事向け特急便 1便 ¥42,000",
        "SecretDiscount": "年間物量コミット達成時 秘密割引 22%", "ApprovedBy": "物流部長・中村",
    },
    {
        "Id": "FRT-2026-002", "Carrier": "ヤマト運輸", "ConfidentialLevel": "CONFIDENTIAL",
        "BaseRate": "1ケース ¥1,620(中部向け)", "CustomerSurcharge": "時間指定便 1便 ¥8,500",
        "SecretDiscount": "繁忙期除外 秘密割引 17%", "ApprovedBy": "物流部長・中村",
    },
]

TABLES = {
    "Shipment": ("shipments", SEED_SHIPMENTS),
    "Stock": ("stocks", SEED_STOCKS),
    "FreightContract": ("freight_contracts", SEED_FREIGHT),
}


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    for _, (table, seed) in TABLES.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        if conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0:
            conn.executemany(
                f"INSERT INTO {table} (id, value) VALUES (?, ?)",
                [(row["Id"], json.dumps(row, ensure_ascii=False)) for row in seed],
            )
    conn.commit()
    return conn


_conn = _init_db()
app = FastAPI(title="Demo Legacy Logistics System", version="1.0.0")

# ---------------------------------------------------------------------------
# 公開経路の境界(CRM と同じ規則)
#   - /api/{entity}/list は Bridge の同期専用。前段プロキシ経由(公開)では 404。
#   - 画面の操作は物流 Bridge の公開デモ経路(/api/a2a/demo/*)へ中継する。回数制限・ペルソナ・
#     応答の許可リストは Bridge 側が担う。ブラウザにも、この画面プロセスにもキーは置かない。
# ---------------------------------------------------------------------------
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-prefix", "x-real-ip", "forwarded")
_LOOPBACK = {"127.0.0.1", "::1"}


def _is_local_direct(request: Request) -> bool:
    if any(h in request.headers for h in _PROXY_HEADERS):
        return False
    try:
        return ipaddress.ip_address(request.client.host if request.client else "").is_loopback
    except ValueError:
        return False


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    if peer in _LOOPBACK:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()
    return peer or "unknown"


@app.middleware("http")
async def _internal_api_gate(request: Request, call_next):
    path = request.scope["path"]
    if path.startswith("/api/") and not path.startswith("/api/a2a-demo/") and not _is_local_direct(request):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)


def _call(method: str, path: str, request: Request, payload: dict | None = None, timeout: float = 120) -> dict:
    headers = {"Content-Type": "application/json"}
    ip = _client_ip(request)
    if ip and ip not in _LOOPBACK:
        headers["X-Forwarded-For"] = ip  # Bridge 側の回数制限を訪問者ごとに効かせる
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    req = urllib.request.Request(f"{LOGI_BRIDGE_URL}{path}", data=data, method=method, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
        except Exception:
            detail = None
        if e.code in (404, 409, 429) and isinstance(detail, str):
            raise HTTPException(status_code=e.code, detail=detail) from None
        log.warning("bridge %s returned %s", path, e.code)
        raise HTTPException(status_code=502, detail="AI連携が一時的に利用できません") from None
    except Exception as e:
        log.warning("bridge %s unreachable: %s", path, e)
        raise HTTPException(status_code=502, detail="AI連携が一時的に利用できません") from None


class DemoAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    persona: Literal["ops", "contract"] = "ops"


class DemoPeerActionBody(BaseModel):
    action: Literal["invite", "approve", "reject", "block", "unblock"]


class DemoInvitationRespondBody(BaseModel):
    decision: Literal["approve", "reject"]


@app.get("/api/a2a-demo/governance")
def demo_governance(request: Request):
    return _call("GET", "/api/a2a/demo/governance", request, timeout=30)


@app.get("/api/a2a-demo/inbound-log")
def demo_inbound_log(request: Request):
    return _call("GET", "/api/a2a/demo/inbound-log", request, timeout=30)


@app.post("/api/a2a-demo/peers/{peer_name}/action")
def demo_peer_action(peer_name: str, body: DemoPeerActionBody, request: Request):
    if peer_name not in ("erp",):
        raise HTTPException(status_code=404, detail="unknown peer")
    return _call("POST", f"/api/a2a/demo/peers/{peer_name}/action", request, {"action": body.action})


@app.post("/api/a2a-demo/invitations/{invite_code}/respond")
def demo_respond_invitation(invite_code: str, body: DemoInvitationRespondBody, request: Request):
    if not invite_code.startswith("inv_") or not invite_code[4:].isalnum() or len(invite_code) > 40:
        raise HTTPException(status_code=404, detail="unknown invitation")
    return _call("POST", f"/api/a2a/demo/invitations/{invite_code}/respond", request, {"decision": body.decision})


@app.post("/api/a2a-demo/reset")
def demo_reset(request: Request):
    return _call("POST", "/api/a2a/demo/reset", request, {})


@app.post("/api/a2a-demo/federated-ask")
def demo_federated_ask(body: DemoAskRequest, request: Request):
    return _call("POST", "/api/a2a/demo/federated-ask", request, {"persona": body.persona, "question": body.question})


@app.post("/api/a2a-demo/acl-probe")
def demo_acl_probe(request: Request):
    return _call("POST", "/api/a2a/demo/acl-probe", request, {"peer": "erp"})


def _load_public_data() -> dict:
    """公開画面向け。運送契約は件数のみで、運賃・秘密割引は渡さない。"""
    def rows(table: str) -> list[dict]:
        return [json.loads(r[0]) for r in _conn.execute(f"SELECT value FROM {table} ORDER BY id").fetchall()]

    return {
        "shipments": rows("shipments"),
        "stocks": rows("stocks"),
        "freight_count": _conn.execute("SELECT COUNT(*) FROM freight_contracts").fetchone()[0],
    }


@app.get("/", response_class=HTMLResponse)
def index():
    data_json = json.dumps(_load_public_data(), ensure_ascii=False).replace("</", "<\\/")
    return _INDEX_HTML.replace("__LOGI_PUBLIC_DATA__", data_json)


@app.get("/api/health")
def health():
    return {"status": "ok", "system": "legacy-logistics"}


@app.get("/api/{entity}/list")
def list_entity(entity: str, limit: int = Query(default=1000, ge=1, le=10000)):
    if entity not in TABLES:
        raise HTTPException(status_code=404, detail=f"Unknown entity: {entity}")
    table, _ = TABLES[entity]
    total = _conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
    rows = [
        json.loads(r[0])
        for r in _conn.execute(f"SELECT value FROM {table} ORDER BY id LIMIT ?", (limit,)).fetchall()
    ]
    return {"entity": entity, "count": total, "rows": rows}


_INDEX_HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>レガシー物流・倉庫管理 × A2A 多段連携デモ | AI-Sync Bridge</title>
<meta name="description" content="ERP・CRM・物流の3つの独立システムを A2A で連携。中継された依頼は権限を縮退して評価し、機密の運送契約はどの Agent にも渡さない多段委譲デモ。">
<style>
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif;margin:0;line-height:1.6;color:#1f2937;background:#f1f5f9}
  .topbar{background:#14532d;color:#fff;padding:.75rem 1.25rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem}
  .brand{display:flex;align-items:center;gap:.6rem;font-weight:700;font-size:1.05rem}
  .brand small{font-weight:400;color:#bbf7d0;font-size:.8rem}
  .toplinks{display:flex;gap:.5rem;flex-wrap:wrap}
  .toplinks a{color:#dcfce7;text-decoration:none;font-size:.84rem;padding:.3rem .65rem;border:1px solid #166534;border-radius:6px}
  .toplinks a:hover{background:#166534;color:#fff}
  .wrap{max-width:1120px;margin:1.25rem auto;padding:0 1rem}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:1rem}
  @media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:.75rem 1rem}
  .kpi .lbl{font-size:.78rem;color:#64748b} .kpi .val{font-size:1.35rem;font-weight:700;color:#0f172a;margin-top:.15rem}
  .tabs{display:flex;gap:.4rem;border-bottom:2px solid #cbd5e1;margin-bottom:1rem;flex-wrap:wrap}
  .tab{padding:.55rem 1rem;border:none;background:transparent;color:#475569;font-weight:600;cursor:pointer;border-bottom:3px solid transparent;margin-bottom:-2px;border-radius:6px 6px 0 0;font-size:.92rem}
  .tab:hover{background:#e2e8f0;color:#0f172a} .tab.active{color:#15803d;border-bottom-color:#16a34a;background:#fff}
  .pane{display:none} .pane.active{display:block}
  .card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.25rem;margin-bottom:1rem}
  .card h3{margin:.25rem 0 .6rem;font-size:1.05rem}
  .sub{color:#64748b;margin:0 0 .75rem;font-size:.9rem}
  .row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
  input[type=text]{flex:1;min-width:240px;padding:.55rem .75rem;border:1px solid #cbd5e1;border-radius:6px;font-size:.92rem}
  select{padding:.5rem;border:1px solid #cbd5e1;border-radius:6px;font-size:.9rem}
  button{padding:.5rem .85rem;border:none;border-radius:6px;background:#16a34a;color:#fff;font-weight:600;cursor:pointer;font-size:.88rem}
  button.sec{background:#0f766e} button.warn{background:#b45309} button.gray{background:#475569} button.sm{padding:.3rem .6rem;font-size:.78rem} button:disabled{opacity:.5}
  .box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:.75rem 1rem}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:.75rem} @media(max-width:760px){.grid{grid-template-columns:1fr}}
  .ans{margin-top:.5rem;white-space:pre-wrap;font-size:.92rem}
  .meta{font-size:.78rem;color:#64748b;margin-top:.35rem}
  .badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.74rem;font-weight:600;background:#e0f2fe;color:#0369a1}
  .badge.red{background:#fee2e2;color:#b91c1c} .badge.green{background:#dcfce7;color:#15803d} .badge.gray{background:#e2e8f0;color:#475569} .badge.amber{background:#fef3c7;color:#92400e}
  .tbl-wrap{overflow-x:auto} table{border-collapse:collapse;width:100%;font-size:.88rem}
  th{background:#f8fafc;color:#475569;font-weight:600} td,th{border-top:1px solid #e2e8f0;padding:.5rem .6rem;text-align:left;vertical-align:top}
  .err{color:#b91c1c;margin-top:.4rem}
  .lock-box{background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:1rem;color:#7f1d1d}
  .topo{display:grid;grid-template-columns:1fr auto 1fr auto 1fr;align-items:center;gap:.4rem;text-align:center;margin:.5rem 0}
  .node{border:2px solid #cbd5e1;border-radius:10px;padding:.6rem;background:#fff;font-weight:700;font-size:.9rem}
  .node small{display:block;font-weight:400;color:#64748b;font-size:.74rem}
  .node.self{border-color:#16a34a;background:#f0fdf4}
  .edge{font-size:.74rem;color:#475569;white-space:nowrap}
  .path{font-family:ui-monospace,Menlo,monospace;font-size:.82rem}
  pre{background:#0f172a;color:#e2e8f0;padding:.75rem;border-radius:8px;overflow:auto;font-size:.78rem}
</style></head>
<body>
  <header class="topbar">
    <div class="brand"><span>🚚 レガシー物流・倉庫管理</span><small>WMS/TMS（Port 5030 / logistics.db）</small></div>
    <div class="toplinks">
      <a href="/erp/ai-panel">🏭 ERP</a><a href="/crm/">📇 CRM</a><a href="/">🏠 トップ</a>
    </div>
  </header>

  <main class="wrap">
    <div class="kpis">
      <div class="kpi"><div class="lbl">出荷・配送 (Shipment)</div><div class="val" id="kpiShp">-</div></div>
      <div class="kpi"><div class="lbl">出荷保留・遅延</div><div class="val" id="kpiHold">-</div></div>
      <div class="kpi"><div class="lbl">倉庫在庫ロット (Stock)</div><div class="val" id="kpiStk">-</div></div>
      <div class="kpi"><div class="lbl">運送契約 (機密)</div><div class="val" id="kpiFrt">-</div></div>
    </div>

    <nav class="tabs">
      <button class="tab active" data-tab="a2a">🛰️ A2A 受信・信頼ポリシー</button>
      <button class="tab" data-tab="ship">🚚 出荷・配送</button>
      <button class="tab" data-tab="stock">📦 倉庫在庫</button>
      <button class="tab" data-tab="freight">🔒 運送契約（機密）</button>
    </nav>

    <section id="pane-a2a" class="pane active">
      <div class="card">
        <h3>1. 3システムの信頼関係（物流 Agent から見た図）</h3>
        <p class="sub">各 Agent は<b>自分の Peer しか知りません</b>。物流は CRM と直接の信頼関係を持たず、CRM の依頼は ERP が中継したときだけ、<b>権限を縮退</b>して受け付けます。</p>
        <div class="topo">
          <div class="node">📇 CRM<small>直接の信頼なし</small></div>
          <div class="edge">— 委譲 →<br><span class="badge gray">CRM⇄ERP</span></div>
          <div class="node">🏭 ERP<small>ハブ / 中継者</small></div>
          <div class="edge">— 委譲・中継 →<br><span class="badge" id="topoErp">確認中</span></div>
          <div class="node self">🚚 物流（自分）<small>Shipment / Stock / 運送契約</small></div>
        </div>
        <div class="tbl-wrap"><table>
          <thead><tr><th>依頼の経路</th><th>物流での評価</th><th>見えるデータ</th></tr></thead>
          <tbody>
            <tr><td class="path">erp → logistics</td><td><span class="badge green">直接</span> ERP Peer キーの主体 <code>a2a_erp_peer</code></td><td>出荷・配送 ＋ 倉庫在庫（ロケーション・引当）</td></tr>
            <tr><td class="path">crm → erp → logistics</td><td><span class="badge amber">中継・縮退</span> <code>relay_roles: [a2a_relay_view]</code></td><td>出荷・配送のみ（倉庫在庫は除外）</td></tr>
            <tr><td class="path">logistics → … → logistics</td><td><span class="badge red">拒否</span> ループ検出</td><td>—</td></tr>
            <tr><td class="path">3ホップ以上</td><td><span class="badge red">拒否</span> <code>max_hops: 2</code> 超過</td><td>—</td></tr>
            <tr><td class="path">（どの経路でも）</td><td><span class="badge red">対象外</span> 物流の契約担当だけ</td><td>運送契約（運賃・秘密割引）</td></tr>
          </tbody>
        </table></div>
        <div class="meta">経路は依頼に付く <code>a2a_chain</code> で運ばれますが、直前の Agent は本文ではなく<b>認証済みのキー</b>から物流が自分で決めます。中継者 ERP の権限を「ERP を経由しただけの CRM」に貸さないため（混乱した代理人問題の防止）。</div>
      </div>

      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem;flex-wrap:wrap">
          <h3 style="margin:0">2. 受信ログ：誰の依頼が、どの経路で届いたか</h3>
          <button id="btnLog" class="sm sec">↻ 更新</button>
        </div>
        <p class="sub" style="margin:.4rem 0 .6rem">CRM（<a href="/crm/" target="_blank">/crm/</a>）で「物流状況も」と質問するか、ERP の A2A タブで「3システム統合」を実行すると、ここに経路付きで記録されます。質問本文は保存しません（ハッシュのみ）。</p>
        <div class="tbl-wrap"><table>
          <thead><tr><th>受信時刻 (UTC)</th><th>経路</th><th>判定</th><th>適用ロール / 理由</th><th>監査#</th></tr></thead>
          <tbody id="logBody"><tr><td colspan="5" class="meta">読み込み中...</td></tr></tbody>
        </table></div>
      </div>

      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem;flex-wrap:wrap">
          <h3 style="margin:0">3. 信頼ポリシーと連携状態（物流 ⇄ ERP）</h3>
          <div class="row"><button id="btnGov" class="sm sec">↻ 状態更新</button><button id="btnReset" class="sm gray">↺ 初期状態に戻す</button></div>
        </div>
        <p class="sub" style="margin:.4rem 0 .6rem">ERP を <b>遮断</b> すると、物流からの送信だけでなく <b>ERP からの受信（直接・中継とも）も 403</b> で止まります。公開デモの変更は全訪問者で共有されるため、<span id="ttl">一定時間</span>後に自動で初期状態へ戻ります。</p>
        <div id="govPeers" class="box" style="margin-bottom:.75rem">読み込み中...</div>
        <div id="govInbox" class="box" style="margin-bottom:.75rem"></div>
        <details><summary style="cursor:pointer;font-weight:600;color:#14532d">bridge.yaml（a2a 部分）を表示</summary><pre id="yaml"></pre></details>
      </div>

      <div class="card">
        <h3>4. 物流 → ERP への問い合わせ ＆ 権限分離の検証</h3>
        <div class="row">
          <select id="persona"><option value="ops">倉庫・配送担当（ERP への委譲可）</option><option value="contract">契約担当（ERP への委譲は不可）</option></select>
          <input id="q" type="text" maxlength="500" value="ORD1015 の受注状況と納期、顧客は誰か教えて">
          <button id="btnAsk">A2A で回答</button>
        </div>
        <div id="askErr" class="err"></div>
        <div id="askOut" class="grid" style="display:none">
          <div class="box"><strong>物流 Agent（自システム）</strong><div id="locAns" class="ans"></div><div id="locSub" class="meta"></div></div>
          <div class="box"><strong>ERP Agent（A2A 委譲先）</strong> <span id="erpBadge" class="badge"></span><div id="erpAns" class="ans"></div><div id="erpSub" class="meta"></div></div>
        </div>
        <div class="row" style="margin-top:.8rem"><button class="warn" id="btnProbe">物流 → ERP: 請求情報（経理限定）を聞き出す</button></div>
        <div id="probeOut" class="box" style="display:none;margin-top:.5rem"></div>
      </div>
    </section>

    <section id="pane-ship" class="pane"><div class="card">
      <h3>🚚 出荷・配送（Shipment）</h3>
      <p class="sub">ERP の受注番号で紐づく出荷実績です。ERP Agent（直接）と、ERP が中継した CRM の依頼（縮退ロール）から参照できます。</p>
      <div class="tbl-wrap"><table><thead><tr><th>出荷ID</th><th>受注</th><th>顧客</th><th>状態</th><th>運送会社</th><th>出荷日</th><th>到着予定</th><th>届け先 / 遅延理由</th></tr></thead><tbody id="shpBody"></tbody></table></div>
    </div></section>

    <section id="pane-stock" class="pane"><div class="card">
      <h3>📦 倉庫在庫（Stock）</h3>
      <p class="sub">倉庫ロケーションと受注への引当です。<b>ERP からの直接の依頼だけ</b>が参照でき、CRM 発の中継依頼からは除外されます。</p>
      <div class="tbl-wrap"><table><thead><tr><th>ロットID</th><th>品目</th><th>倉庫 / ロケーション</th><th>在庫</th><th>引当</th><th>引当受注</th><th>次回入荷</th></tr></thead><tbody id="stkBody"></tbody></table></div>
    </div></section>

    <section id="pane-freight" class="pane"><div class="card">
      <h3>🔒 運送契約（FreightContract）</h3>
      <div class="lock-box"><strong>物流 契約担当限定（閲覧制限中）</strong>
        <p style="margin:.35rem 0 0;font-size:.9rem"><code>logistics.db</code> に <b id="frtCount">-</b> 件の運送契約（基本運賃・特急便料金・秘密割引率）があります。ERP Agent・CRM Agent のどちらにも、直接・中継を問わず渡しません。</p></div>
      <div class="meta">業務データの API は AI-Sync Bridge の同期専用で、公開経路からは読めません。データは毎日 04:10 に初期状態へ戻ります。架空のサンプルであり、実在の企業とは関係ありません。</div>
    </div></section>
  </main>

<script>
const D = __LOGI_PUBLIC_DATA__;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
function switchTab(n) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === n));
  document.querySelectorAll('.pane').forEach((p) => p.classList.toggle('active', p.id === 'pane-' + n));
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => switchTab(t.dataset.tab)));
async function api(method, url, body) {
  const r = await fetch(url, {method, headers: {'Content-Type': 'application/json'}, body: body ? JSON.stringify(body) : undefined});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
  return d;
}
(function init() {
  const s = D.shipments || [], k = D.stocks || [];
  $('kpiShp').textContent = s.length + ' 件';
  $('kpiHold').textContent = s.filter((x) => x.Status === '出荷保留').length + ' 件';
  $('kpiStk').textContent = k.length + ' ロット';
  $('kpiFrt').textContent = (D.freight_count ?? 0) + ' 件 (契約担当限定)';
  $('frtCount').textContent = D.freight_count ?? 0;
  const stc = (v) => v === '出荷保留' ? 'red' : v === '配達完了' ? 'green' : 'amber';
  $('shpBody').innerHTML = s.map((x) => `<tr><td><code>${esc(x.Id)}</code></td><td><code>${esc(x.OrderId)}</code></td>
    <td><strong>${esc(x.CustomerName)}</strong><div class="meta">${esc(x.CustomerId)}</div></td>
    <td><span class="badge ${stc(x.Status)}">${esc(x.Status)}</span></td><td>${esc(x.Carrier)}</td><td>${esc(x.ShipDate || '—')}</td><td>${esc(x.ETA)}</td>
    <td>${esc(x.Destination)}${x.DelayReason ? `<div class="meta" style="color:#b91c1c">${esc(x.DelayReason)}</div>` : ''}</td></tr>`).join('');
  $('stkBody').innerHTML = k.map((x) => `<tr><td><code>${esc(x.Id)}</code></td><td>${esc(x.ProductName)}<div class="meta">${esc(x.ProductId)}</div></td>
    <td>${esc(x.Warehouse)}<div class="meta">${esc(x.Location)}</div></td><td>${esc(x.OnHand)}</td><td>${esc(x.Allocated)}</td>
    <td>${x.AllocatedOrderId ? `<code>${esc(x.AllocatedOrderId)}</code>` : '—'}</td><td>${esc(x.NextInbound || '—')}</td></tr>`).join('');
})();

async function loadLog() {
  try {
    const d = await api('GET', 'api/a2a-demo/inbound-log');
    const items = d.items || [];
    $('logBody').innerHTML = items.length ? items.map((i) => {
      const path = [...(i.path || []), d.agent_id || 'logistics'].join(' → ');
      const judge = i.kind === 'rejected' ? '<span class="badge red">拒否</span>'
        : i.attenuated ? '<span class="badge amber">中継・縮退</span>' : '<span class="badge green">直接</span>';
      const detail = i.kind === 'rejected' ? esc(i.reason || '') : i.attenuated ? `<code>${esc((i.effective_roles || []).join(', '))}</code>` : 'Peer キーの主体のまま';
      return `<tr><td>${esc(i.ts)}</td><td class="path">${esc(path)}</td><td>${judge}</td><td>${detail}</td><td>${esc(i.audit_seq)}</td></tr>`;
    }).join('') : '<tr><td colspan="5" class="meta">まだ受信はありません。CRM または ERP から物流に関わる質問をしてみてください。</td></tr>';
  } catch (e) { $('logBody').innerHTML = `<tr><td colspan="5" class="err">取得エラー: ${esc(e.message)}</td></tr>`; }
}

const ST = {active: ['green', '連携中'], invited: ['', '招待中'], rejected: ['red', '拒否済'], blocked: ['gray', '遮断中']};
async function loadGov() {
  try {
    const d = await api('GET', 'api/a2a-demo/governance');
    $('yaml').textContent = d.yaml_snippet || '';
    $('ttl').textContent = Math.round((d.governance_ttl_sec || 600) / 60) + '分' + (d.governance_expires_in != null ? `（あと約${Math.ceil(d.governance_expires_in / 60)}分で復元）` : '');
    const erp = (d.peers || []).find((p) => p.name === 'erp');
    if (erp) { const [c, l] = ST[erp.status] || ['gray', erp.status]; $('topoErp').className = 'badge ' + c; $('topoErp').textContent = l; }
    $('govPeers').innerHTML = '<strong>登録済み Peer</strong>' + (d.peers || []).map((p) => {
      const [c, l] = ST[p.status] || ['gray', p.status];
      const b = [];
      if (p.status === 'active') { b.push(`<button class="sm" data-act="invite">✉️ 招待送信</button>`); b.push(`<button class="sm gray" data-act="block">🚫 遮断</button>`); }
      if (p.status === 'blocked') b.push(`<button class="sm" data-act="unblock">🔓 遮断解除</button>`);
      if (p.status === 'rejected') b.push(`<button class="sm" data-act="invite">✉️ 再招待</button>`);
      return `<div style="display:flex;justify-content:space-between;gap:.5rem;flex-wrap:wrap;margin-top:.5rem;padding-top:.5rem;border-top:1px solid #e2e8f0">
        <div><strong>${esc(p.name.toUpperCase())} Agent</strong> <span class="badge ${c}">${esc(l)}</span>
          <div class="meta">受信主体の固定: ${p.inbound_bound ? '✅ inbound_user_id 設定済' : '⚠️ 未設定'} · 中継依頼: ${p.accepts_relay ? '縮退して受理' : '拒否'} · 委譲上限: <code>${esc((p.allowed_roles || []).join(', ') || '全ロール')}</code>${p.invite_code ? ' · 招待 <code>' + esc(p.invite_code) + '</code>' : ''}</div></div>
        <div class="row" data-peer="${esc(p.name)}">${b.join('')}</div></div>`;
    }).join('');
    const invs = d.incoming_invitations || [];
    $('govInbox').innerHTML = '<strong>📥 受信した招待</strong>' + (invs.length ? invs.map((i) => `<div style="display:flex;justify-content:space-between;gap:.5rem;margin-top:.5rem;padding-top:.5rem;border-top:1px solid #e2e8f0;flex-wrap:wrap">
      <div><strong>${esc(i.from_agent)}</strong> <span class="badge">${esc(i.status)}</span><div class="meta">差出人(キーから判定): <code>${esc(i.from_peer_name)}</code> · ${esc(i.note)}</div></div>
      <div class="row">${i.status === 'pending' ? `<button class="sm" data-inv="${esc(i.invite_code)}" data-dec="approve">✅ 承認</button><button class="sm warn" data-inv="${esc(i.invite_code)}" data-dec="reject">✖ 拒否</button>` : ''}</div></div>`).join('') : '<div class="meta">なし（ERP の A2A タブから物流へ招待を送ると届きます）</div>');
    $('govPeers').querySelectorAll('button[data-act]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try { await api('POST', 'api/a2a-demo/peers/' + encodeURIComponent(b.parentElement.dataset.peer) + '/action', {action: b.dataset.act}); } catch (e) { alert('操作失敗: ' + e.message); }
      loadGov();
    }));
    $('govInbox').querySelectorAll('button[data-inv]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try { await api('POST', 'api/a2a-demo/invitations/' + encodeURIComponent(b.dataset.inv) + '/respond', {decision: b.dataset.dec}); } catch (e) { alert('応答失敗: ' + e.message); }
      loadGov();
    }));
  } catch (e) { $('govPeers').textContent = '取得エラー: ' + e.message; }
}

const LBL = {completed: '完了', forbidden: '委譲不可(方針)', blocked: '遮断中', error: 'エラー', unreachable: '接続不可', refused: '相手が拒否'};
$('btnAsk').addEventListener('click', async () => {
  const b = $('btnAsk'); b.disabled = true; $('askErr').textContent = '';
  try {
    const d = await api('POST', 'api/a2a-demo/federated-ask', {question: $('q').value, persona: $('persona').value});
    $('askOut').style.display = 'grid';
    const loc = d.local || {}, erp = (d.peers || []).find((p) => p.peer === 'erp') || {};
    $('locAns').textContent = loc.answer || '(回答なし)';
    $('locSub').textContent = `権限で除外 ${loc.acl_filtered ?? 0} 件 · 監査ID ${String(loc.audit_id || '').slice(0, 8)}`;
    $('erpBadge').textContent = LBL[erp.status] || erp.status || '';
    $('erpBadge').className = 'badge ' + (erp.status === 'completed' ? 'green' : erp.status === 'forbidden' ? 'gray' : 'red');
    $('erpAns').textContent = erp.status === 'forbidden' ? 'このロールは ERP への委譲が許可されていません（物流側の allowed_roles）。' : (erp.answer || erp.error || '(応答なし)');
    $('erpSub').textContent = erp.status === 'completed' ? `ERP 側で除外 ${erp.acl_filtered ?? 0} 件 · ${erp.latency_ms ?? '-'} ms · ERP 監査ID ${String(erp.audit_id || '').slice(0, 8)}` : '';
  } catch (e) { $('askErr').textContent = 'エラー: ' + e.message; }
  finally { b.disabled = false; loadLog(); }
});
$('btnProbe').addEventListener('click', async () => {
  const b = $('btnProbe'), o = $('probeOut'); b.disabled = true; o.style.display = 'block'; o.textContent = '検証中...';
  try {
    const d = await api('POST', 'api/a2a-demo/acl-probe');
    o.innerHTML = `${d.leaked ? '<span class="badge red">漏えいを検出</span>' : '<span class="badge green">PASS: 機密は返されていません</span>'}
      <div class="meta">質問: ${esc(d.question)} · 狙った機密: <code>${esc(d.secret_entity || '')}</code></div>
      <div class="ans">${esc(d.answer || d.error || '(回答なし)')}</div><div class="meta">状態 ${esc(d.state)} · ERP 側で除外 ${esc(d.acl_filtered ?? 0)} 件 · 監査ID ${esc(String(d.audit_id || '').slice(0, 8))}</div>`;
  } catch (e) { o.innerHTML = `<span class="err">エラー: ${esc(e.message)}</span>`; }
  finally { b.disabled = false; }
});
$('btnLog').addEventListener('click', loadLog);
$('btnGov').addEventListener('click', loadGov);
$('btnReset').addEventListener('click', async () => { try { await api('POST', 'api/a2a-demo/reset'); } catch (e) { alert(e.message); } loadGov(); });
loadLog(); loadGov();
</script>
</body></html>"""
