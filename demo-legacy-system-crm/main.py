"""
Demo Legacy CRM System (Sales & Customer Support) — Port 5020.

Loosely coupled with ERP (demo-legacy-system, Port 5010) via CustomerId (C0001..)
and OrderId. The OrderIds below are real rows of the ERP fixed seed (data.py), e.g.
ORD1015 = 山田商事 / 確認中 / 納期 2026-08-24 — keep them in sync if the ERP seed changes. Keeps confidential customer contracts & compensation terms
isolated in its own SQLite database (crm.db).
"""
from __future__ import annotations

import ipaddress
import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from collections import OrderedDict, deque
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel, Field

log = logging.getLogger("legacy-crm")

DB_PATH = os.getenv("AISB_CRM_DB_PATH", str(Path(__file__).resolve().parent / "crm.db"))
CRM_BRIDGE_URL = os.getenv("AISB_CRM_BRIDGE_URL", "http://127.0.0.1:5021").rstrip("/")
ERP_BRIDGE_URL = os.getenv("AISB_ERP_BRIDGE_URL", "http://127.0.0.1:5011").rstrip("/")
# この画面プロセスは A2A キーを持たない(Peer 間の通信と ACL 検証は各 Bridge が行う)

SEED_ACCOUNTS = [
    {
        "Id": "ACC-001",
        "CustomerId": "C0001",
        "CustomerName": "山田商事",
        "Tier": "VIP",
        "AccountOwner": "営業部・佐藤",
        "AnnualRevenue": 48000000,
        "RenewalDate": "2026-12-31",
        "Notes": "重点VIP顧客。来月大型追加発注(約1,200万円)の商談中。納期遅延に極めて敏感。",
    },
    {
        "Id": "ACC-002",
        "CustomerId": "C0002",
        "CustomerName": "佐藤工業",
        "Tier": "Enterprise",
        "AccountOwner": "営業部・鈴木",
        "AnnualRevenue": 32000000,
        "RenewalDate": "2027-03-31",
        "Notes": "店舗設備の定期購入顧客。保守部品の即納体制を重視。",
    },
    {
        "Id": "ACC-003",
        "CustomerId": "C0003",
        "CustomerName": "鈴木商店",
        "Tier": "Standard",
        "AccountOwner": "営業部・高橋",
        "AnnualRevenue": 12000000,
        "RenewalDate": "2026-09-30",
        "Notes": "価格感度が高く、競合他社からの切替提案を受けている。",
    },
    {
        "Id": "ACC-004",
        "CustomerId": "C0004",
        "CustomerName": "高橋物産",
        "Tier": "VIP",
        "AccountOwner": "営業部・佐藤",
        "AnnualRevenue": 55000000,
        "RenewalDate": "2027-01-31",
        "Notes": "全国拠点向け一括納入契約。四半期ごとに品質レビューを実施。",
    },
]

SEED_TICKETS = [
    {
        "Id": "TCK-2026-001",
        "CustomerId": "C0001",
        "CustomerName": "山田商事",
        "OrderId": "ORD1015",
        "Severity": "High",
        "Status": "Open",
        "Subject": "受注 ORD1015 の納期遅延に関するクレーム",
        "Summary": "山田商事より注文 ORD1015(納期 2026-08-24)が未出荷のままとの緊急クレーム。最短の出荷日と来月大型案件への影響確認を要求されている。",
        "CreatedAt": "2026-11-24",
    },
    {
        "Id": "TCK-2026-002",
        "CustomerId": "C0002",
        "CustomerName": "佐藤工業",
        "OrderId": "ORD1032",
        "Severity": "Medium",
        "Status": "InProgress",
        "Subject": "受注 ORD1032 の納期確認と予備在庫の引当依頼",
        "Summary": "佐藤工業より ORD1032(納期 2026-09-17)の納期確認と予備品確保について問い合わせ。ERP側の受注状況と在庫を確認中。",
        "CreatedAt": "2026-11-22",
    },
    {
        "Id": "TCK-2026-003",
        "CustomerId": "C0004",
        "CustomerName": "高橋物産",
        "OrderId": "ORD1025",
        "Severity": "Low",
        "Status": "Resolved",
        "Subject": "出荷済み ORD1025 の検収書類の再送依頼",
        "Summary": "高橋物産より出荷済みの ORD1025 について検収書類の再送依頼。送付済みでクローズ。",
        "CreatedAt": "2026-11-18",
    },
]

# Confidential contracts — ONLY visible to crm_legal / crm_manager, NEVER to ERP peer
SEED_CONTRACTS = [
    {
        "Id": "CTR-2026-001",
        "CustomerId": "C0001",
        "CustomerName": "山田商事",
        "ConfidentialLevel": "STRICTLY_CONFIDENTIAL",
        "PenaltyClause": "納期遅延が5営業日を超過した場合、受注金額の15%を違約金として返金し、次期契約を10%特別値引する。",
        "MaxDiscountRate": "18%",
        "ApprovedBy": "法務部長・田中",
    },
    {
        "Id": "CTR-2026-002",
        "CustomerId": "C0004",
        "CustomerName": "高橋物産",
        "ConfidentialLevel": "STRICTLY_CONFIDENTIAL",
        "PenaltyClause": "SLA違反時の無償代替機提供および年間リベート8%の秘密合意あり。",
        "MaxDiscountRate": "12%",
        "ApprovedBy": "法務部長・田中",
    },
]

TABLES = {
    "Account": ("accounts", SEED_ACCOUNTS),
    "Ticket": ("tickets", SEED_TICKETS),
    "Contract": ("contracts", SEED_CONTRACTS),
}


def _init_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    for _, (table, seed) in TABLES.items():
        conn.execute(f"CREATE TABLE IF NOT EXISTS {table} (id TEXT PRIMARY KEY, value TEXT NOT NULL)")
        count = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        if count == 0:
            conn.executemany(
                f"INSERT INTO {table} (id, value) VALUES (?, ?)",
                [(row["Id"], json.dumps(row, ensure_ascii=False)) for row in seed],
            )
    conn.commit()
    return conn


_conn = _init_db()
app = FastAPI(title="Demo Legacy CRM System", version="1.0.0")


# ---------------------------------------------------------------------------
# 公開経路の境界
#   - 業務データの一覧API(/api/{entity}/list)は Bridge の同期専用。前段プロキシ経由(公開)では 404。
#     機密契約(Contract)が素の API で読めると「ERP からは見えない」というデモの前提が崩れる。
#   - 画面の操作は CRM Bridge の公開デモ経路(/api/a2a/demo/*)へ中継する。ペルソナ・回数制限・
#     応答の許可リスト・会話の破棄は Bridge 側の DemoGateway が担う。ブラウザにキーは渡さない。
#   - ACL 検証は Peer キーを使うため、この画面側でも IP ごとに回数を絞る。
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
    """ai-api-server の client_ip と同じ規則: ローカルの前段プロキシが付けた末尾の値だけを信用する。"""
    peer = request.client.host if request.client else ""
    if peer in _LOOPBACK:
        fwd = request.headers.get("x-forwarded-for", "")
        if fwd:
            return fwd.split(",")[-1].strip()
    return peer or "unknown"


class _Limiter:
    def __init__(self, limit: int, window_sec: float, max_keys: int = 10000):
        self.limit, self.window, self.max_keys = limit, window_sec, max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            self._hits.move_to_end(key)
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True


_acl_check_limiter = _Limiter(20, 3600)


@app.middleware("http")
async def _internal_api_gate(request: Request, call_next):
    path = request.scope["path"]
    if path.startswith("/api/") and not path.startswith("/api/a2a-demo/") and not _is_local_direct(request):
        return JSONResponse({"detail": "Not Found"}, status_code=404)
    return await call_next(request)


def _post_json(url: str, payload: dict, *, api_key: str = "", client_ip: str | None = None) -> dict:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    if client_ip and client_ip not in _LOOPBACK:
        headers["X-Forwarded-For"] = client_ip  # Bridge 側の回数制限を訪問者ごとに効かせる
    req = urllib.request.Request(url, data=data, method="POST", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Bridge の公開経路の detail は公開してよい文言だけ。それ以外(5xx 等)は中身を返さない
        try:
            detail = json.loads(e.read().decode("utf-8")).get("detail")
        except Exception:
            detail = None
        if e.code in (404, 409, 429) and isinstance(detail, str):
            raise HTTPException(status_code=e.code, detail=detail) from None
        log.warning("bridge %s returned %s", url, e.code)
        raise HTTPException(status_code=502, detail="AI連携が一時的に利用できません") from None
    except Exception as e:
        log.warning("bridge %s unreachable: %s", url, e)
        raise HTTPException(status_code=502, detail="AI連携が一時的に利用できません") from None


def _get_json(url: str, *, client_ip: str | None = None) -> dict:
    headers = {}
    if client_ip and client_ip not in _LOOPBACK:
        headers["X-Forwarded-For"] = client_ip
    req = urllib.request.Request(url, method="GET", headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        log.warning("bridge GET %s failed: %s", url, e)
        raise HTTPException(status_code=502, detail="AI連携が一時的に利用できません") from None


class DemoAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=500)
    persona: Literal["support", "legal"] = "support"


class DemoPeerActionBody(BaseModel):
    action: Literal["invite", "approve", "reject", "block", "unblock"]


class DemoInvitationRespondBody(BaseModel):
    decision: Literal["approve", "reject"]


@app.get("/api/a2a-demo/governance")
def demo_governance(request: Request):
    return _get_json(f"{CRM_BRIDGE_URL}/api/a2a/demo/governance", client_ip=_client_ip(request))


@app.post("/api/a2a-demo/peers/{peer_name}/action")
def demo_peer_action(peer_name: str, body: DemoPeerActionBody, request: Request):
    return _post_json(
        f"{CRM_BRIDGE_URL}/api/a2a/demo/peers/{peer_name}/action",
        {"action": body.action},
        client_ip=_client_ip(request),
    )


@app.post("/api/a2a-demo/invitations/{invite_code}/respond")
def demo_respond_invitation(invite_code: str, body: DemoInvitationRespondBody, request: Request):
    return _post_json(
        f"{CRM_BRIDGE_URL}/api/a2a/demo/invitations/{invite_code}/respond",
        {"decision": body.decision},
        client_ip=_client_ip(request),
    )


@app.post("/api/a2a-demo/reset")
def demo_reset(request: Request):
    return _post_json(f"{CRM_BRIDGE_URL}/api/a2a/demo/reset", {}, client_ip=_client_ip(request))


@app.post("/api/a2a-demo/federated-ask")
def demo_federated_ask(body: DemoAskRequest, request: Request):
    return _post_json(
        f"{CRM_BRIDGE_URL}/api/a2a/demo/federated-ask",
        {"persona": body.persona, "question": body.question},
        client_ip=_client_ip(request),
    )


# ACL 検証は各 Bridge の公開デモ経路(/api/a2a/demo/acl-probe)に任せる。機密を狙う質問は
# 各 Bridge の bridge.yaml(peers[].acl_probe)で固定され、Peer キーは Bridge の外に出ない。
# 以前はこの画面プロセスが ERP→CRM / CRM→ERP 両方の Peer キーを持ち、ERP になりすませる状態だった。
_ACL_PROBE_ROUTES = {
    # 方向: (検証を実行する Bridge, その Bridge から見た相手 Peer)
    "erp_to_crm": (ERP_BRIDGE_URL, "crm"),
    "crm_to_erp": (CRM_BRIDGE_URL, "erp"),
}


@app.post("/api/a2a-demo/acl-check")
def demo_acl_check(request: Request, direction: Literal["erp_to_crm", "crm_to_erp"] = Query(default="erp_to_crm")):
    if not _acl_check_limiter.allow(_client_ip(request)):
        raise HTTPException(status_code=429, detail="検証の利用回数の上限に達しました。しばらくしてからお試しください")
    bridge_url, peer = _ACL_PROBE_ROUTES[direction]
    d = _post_json(f"{bridge_url}/api/a2a/demo/acl-probe", {"peer": peer}, client_ip=_client_ip(request))
    return {
        "direction": direction,
        "question": d.get("question"),
        "agent": {"crm": "CRM Support & Sales Agent", "erp": "Manufacturing ERP Agent"}[peer],
        "state": d.get("state"),
        "answer": d.get("answer") or d.get("error") or "",
        "acl_filtered": d.get("acl_filtered"),
        "audit_id": d.get("audit_id"),
        "leaked": bool(d.get("leaked")),
    }


def _load_public_crm_data() -> dict:
    """公開画面向けデータ。Contract は機密のため件数のみ返し、本文・違約金は絶対に渡さない。"""
    accounts = [
        json.loads(r[0])
        for r in _conn.execute("SELECT value FROM accounts ORDER BY id").fetchall()
    ]
    tickets = [
        json.loads(r[0])
        for r in _conn.execute("SELECT value FROM tickets ORDER BY id").fetchall()
    ]
    contract_count = _conn.execute("SELECT COUNT(*) FROM contracts").fetchone()[0]
    return {"accounts": accounts, "tickets": tickets, "contract_count": contract_count}


@app.get("/", response_class=HTMLResponse)
def index():
    data_json = json.dumps(_load_public_crm_data(), ensure_ascii=False).replace("</", "<\\/")
    return _INDEX_HTML.replace("__CRM_PUBLIC_DATA__", data_json)


_INDEX_HTML = """<!doctype html>
<html lang="ja"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>レガシーCRM 業務システム × A2A 連携デモ | AI-Sync Bridge</title>
<style>
  *{box-sizing:border-box}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI","Hiragino Sans","Noto Sans JP",sans-serif;margin:0;line-height:1.6;color:#1f2937;background:#f1f5f9}
  .topbar{background:#0f172a;color:#fff;padding:.75rem 1.25rem;display:flex;align-items:center;justify-content:space-between;flex-wrap:wrap;gap:.75rem}
  .brand{display:flex;align-items:center;gap:.6rem;font-weight:700;font-size:1.05rem}
  .brand small{font-weight:400;color:#94a3b8;font-size:.8rem}
  .toplinks{display:flex;gap:.5rem;align-items:center;flex-wrap:wrap}
  .toplinks a{color:#cbd5e1;text-decoration:none;font-size:.84rem;padding:.3rem .65rem;border:1px solid #334155;border-radius:6px}
  .toplinks a:hover{background:#1e293b;color:#fff}
  .wrap{max-width:1120px;margin:1.25rem auto;padding:0 1rem}
  .kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:.75rem;margin-bottom:1rem}
  @media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}}
  .kpi{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:.75rem 1rem}
  .kpi .lbl{font-size:.78rem;color:#64748b}
  .kpi .val{font-size:1.35rem;font-weight:700;color:#0f172a;margin-top:.15rem}
  .tabs{display:flex;gap:.4rem;border-bottom:2px solid #cbd5e1;margin-bottom:1rem;flex-wrap:wrap}
  .tab{padding:.55rem 1rem;border:none;background:transparent;color:#475569;font-weight:600;cursor:pointer;border-bottom:3px solid transparent;margin-bottom:-2px;border-radius:6px 6px 0 0;font-size:.92rem}
  .tab:hover{background:#e2e8f0;color:#0f172a}
  .tab.active{color:#1d4ed8;border-bottom-color:#2563eb;background:#fff}
  .pane{display:none}
  .pane.active{display:block}
  .card{background:#fff;border:1px solid #e2e8f0;border-radius:10px;padding:1rem 1.25rem;margin-bottom:1rem;box-shadow:0 1px 2px rgba(0,0,0,.03)}
  .card h3{margin-top:.25rem;margin-bottom:.6rem;font-size:1.05rem}
  .sub{color:#64748b;margin:0 0 .75rem;font-size:.9rem}
  .row{display:flex;gap:.5rem;flex-wrap:wrap;align-items:center}
  input[type=text]{flex:1;min-width:240px;padding:.55rem .75rem;border:1px solid #cbd5e1;border-radius:6px;font-size:.92rem}
  select{padding:.5rem;border:1px solid #cbd5e1;border-radius:6px;font-size:.9rem}
  button{padding:.5rem .85rem;border:none;border-radius:6px;background:#2563eb;color:#fff;font-weight:600;cursor:pointer;font-size:.88rem}
  button.sec{background:#0f766e} button.warn{background:#b45309} button.sm{padding:.3rem .6rem;font-size:.78rem} button:disabled{opacity:.5}
  .grid{display:grid;grid-template-columns:1fr 1fr;gap:1rem;margin-top:.75rem}
  @media(max-width:760px){.grid{grid-template-columns:1fr}}
  .box{background:#f8fafc;border:1px solid #e2e8f0;border-radius:8px;padding:.75rem 1rem}
  .ans{margin-top:.5rem;white-space:pre-wrap;font-size:.92rem}
  .meta{font-size:.78rem;color:#64748b;margin-top:.35rem}
  .badge{display:inline-block;padding:2px 8px;border-radius:999px;font-size:.74rem;font-weight:600;background:#e0f2fe;color:#0369a1}
  .badge.red{background:#fee2e2;color:#b91c1c} .badge.green{background:#dcfce7;color:#15803d} .badge.gray{background:#e2e8f0;color:#475569} .badge.amber{background:#fef3c7;color:#92400e}
  .tbl-wrap{overflow-x:auto}
  table{border-collapse:collapse;width:100%;font-size:.88rem}
  th{background:#f8fafc;color:#475569;font-weight:600}
  td,th{border-top:1px solid #e2e8f0;padding:.5rem .6rem;text-align:left;vertical-align:top}
  tr:hover td{background:#f8fafc}
  .err{color:#b91c1c;margin-top:.4rem}
  .lock-box{background:#fef2f2;border:1px solid #fecaca;border-radius:8px;padding:1rem;color:#7f1d1d}
</style></head>
<body>
  <header class="topbar">
    <div class="brand">
      <span>📇 レガシーCRM</span>
      <small>営業・クレーム管理システム（Port 5020 / crm.db）</small>
    </div>
    <div class="toplinks">
      <a href="/erp/ai-panel">🏭 ERPデモを開く</a>
      <a href="/logistics/">🚚 物流デモを開く</a>
      <a href="/">🏠 トップへ戻る</a>
    </div>
  </header>

  <main class="wrap">
    <div class="kpis">
      <div class="kpi"><div class="lbl">登録顧客 (Account)</div><div class="val" id="kpiAcc">-</div></div>
      <div class="kpi"><div class="lbl">クレーム・問合せ (Ticket)</div><div class="val" id="kpiTck">-</div></div>
      <div class="kpi"><div class="lbl">対応中クレーム (Open/進行中)</div><div class="val" id="kpiOpen">-</div></div>
      <div class="kpi"><div class="lbl">機密契約 (Contract)</div><div class="val" id="kpiCtr">-</div></div>
    </div>

    <nav class="tabs" role="tablist">
      <button class="tab active" data-tab="a2a">🤝 A2A連携コンソール</button>
      <button class="tab" data-tab="accounts">🏢 顧客マスタ (Account)</button>
      <button class="tab" data-tab="tickets">🎫 クレーム・問合せ (Ticket)</button>
      <button class="tab" data-tab="contracts">🔒 機密契約・権限 (Contract)</button>
    </nav>

    <!-- Tab 1: A2A Console -->
    <section id="pane-a2a" class="pane active">
      <div class="card">
        <h3>1. 跨システム連携回答（CRM → ERP）</h3>
        <p class="sub">ERP とは DB・権限・監査チェーンを共有しない独立システムです。顧客コード(<code>C0001</code>…)と受注番号(<code>ORD1015</code>…)だけで疎結合し、A2A で ERP Agent に問い合わせます。</p>
        <div class="row">
          <select id="persona" title="CRM 側の利用者">
            <option value="support">サポート担当（ERP への委譲可）</option>
            <option value="legal">法務（ERP への委譲は不可）</option>
          </select>
          <input id="q" type="text" maxlength="500" value="山田商事(C0001)の注文 ORD1015 のクレーム状況と、ERP 側の受注・出荷状況は？">
          <button id="btnAsk">A2A 連携で回答</button>
        </div>
        <div class="row" style="margin-top:.4rem">
          <span class="meta" style="margin:0">シナリオ:</span>
          <button class="sm sec" data-scn="山田商事(C0001)の注文 ORD1015 のクレーム状況と、ERP 側の受注・出荷状況は？">📦 受注＋クレーム</button>
          <button class="sm sec" data-scn="ORD1015 はいつ届く？出荷が止まっている理由と、倉庫の引当・ロケーションも教えて">🚚 3システム多段（CRM→ERP→物流）</button>
          <button class="sm sec" data-scn="山田商事の機密契約の違約金は何％？">🔒 機密契約（法務で試す）</button>
        </div>
        <div class="meta">CRM Agent が自分の権限で回答しつつ、同じ質問を A2A で ERP Agent へ委譲します。委譲可否は CRM 側の方針(<code>allowed_roles</code>)で制御されます。</div>
        <div id="fedErr" class="err"></div>
        <div id="fedOut" style="display:none">
          <div class="grid">
            <div class="box"><div><strong>CRM Agent（自システム）</strong> <span id="crmMeta" class="badge"></span></div>
              <div id="crmAns" class="ans"></div><div id="crmSub" class="meta"></div></div>
            <div class="box"><div><strong>ERP Agent（A2A 委譲先）</strong> <span id="erpMeta" class="badge"></span></div>
              <div id="erpAns" class="ans"></div><div id="erpSub" class="meta"></div></div>
          </div>
          <div id="relayBox" class="box" style="display:none;margin-top:1rem;border-left:4px solid #d97706">
            <div><strong>🚚 物流 Agent（ERP が中継）</strong> <span id="relayMeta" class="badge amber"></span></div>
            <div class="meta" id="relayPath"></div>
            <div id="relayAns" class="ans"></div><div id="relaySub" class="meta"></div>
          </div>
        </div>
      </div>

      <div class="card">
        <h3>2. 双方向の権限分離を検証（Opaque Agent の境界）</h3>
        <div class="row">
          <button class="warn" data-dir="erp_to_crm">ERP → CRM: 機密契約の違約金(15%)を聞き出す</button>
          <button class="sec" data-dir="crm_to_erp">CRM → ERP: 従業員の給与を聞き出す</button>
        </div>
        <div class="meta">相手 Agent に与えたキーの権限で A2A タスクを送り、機密が応答（引用・成果物を含む）に出ないことを確認します。</div>
        <div id="aclErr" class="err"></div>
        <div id="aclOut" style="display:none;margin-top:.5rem" class="box">
          <div id="aclBadge"></div><div id="aclQ" class="meta"></div><div id="aclAns" class="ans"></div><div id="aclSub" class="meta"></div>
        </div>
      </div>

      <div class="card">
        <div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem;flex-wrap:wrap">
          <h3 style="margin:0">3. 実システム間の相互招待・承認（ERP ⇄ CRM）</h3>
          <div style="display:flex;gap:.4rem">
            <button id="btnGovRefresh" class="sm sec">↻ 状態更新</button>
            <button id="btnGovReset" class="sm sec">↺ 初期状態に戻す</button>
          </div>
        </div>
        <p class="sub" style="margin:.4rem 0 .8rem">
          ERP 側（<a href="/erp/ai-panel" target="_blank">/erp/ai-panel</a> の「A2A連携 → 発見・認証・管理」）から招待を送ると、下の「受信した招待」にリアルタイムで届きます。CRM 側から ERP へ招待を送ることもできます。
        </p>
        <div id="govPeers" class="box" style="margin-bottom:.75rem">読み込み中...</div>
        <div id="govInbox" class="box">受信した招待を確認中...</div>
      </div>
    </section>

    <!-- Tab 2: Accounts -->
    <section id="pane-accounts" class="pane">
      <div class="card">
        <h3>🏢 顧客マスタ一覧（Account）</h3>
        <p class="sub">営業・サポート・ERP Agent から参照可能な顧客基本情報です。各行のボタンから ERP 側と横断確認できます。</p>
        <div class="tbl-wrap">
          <table>
            <thead>
              <tr><th>顧客コード</th><th>顧客名</th><th>ランク</th><th>担当</th><th>年間取引額</th><th>更新日</th><th>備考</th><th>連携</th></tr>
            </thead>
            <tbody id="accBody"></tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- Tab 3: Tickets -->
    <section id="pane-tickets" class="pane">
      <div class="card">
        <h3>🎫 クレーム・問合せ一覧（Ticket）</h3>
        <p class="sub">ERP の受注番号（<code>ORD1015</code> 等）と紐づくサポート履歴です。「ERP状況をA2Aで確認」から即座に跨システム回答を実行できます。</p>
        <div class="tbl-wrap">
          <table>
            <thead>
              <tr><th>ID</th><th>重要度</th><th>状態</th><th>顧客</th><th>関連受注</th><th>件名・概要</th><th>登録日</th><th>連携</th></tr>
            </thead>
            <tbody id="tckBody"></tbody>
          </table>
        </div>
      </div>
    </section>

    <!-- Tab 4: Contracts & ACL -->
    <section id="pane-contracts" class="pane">
      <div class="card">
        <h3>🔒 機密契約（Contract）とデータ権限境界</h3>
        <div class="lock-box">
          <strong>法務限定データ（閲覧制限中）</strong>
          <p style="margin:.35rem 0 0;font-size:.9rem">
            現在 <code>crm.db</code> 内には <b id="ctrCountText">-</b> 件の機密契約（違約金条項・最大値引率等）が保管されていますが、
            公開画面および ERP Agent からは直接閲覧できないよう隔離されています。
            A2A 連携コンソールの「法務」ロールまたは権限分離テストで ACL 保護の挙動を確認できます。
          </p>
        </div>
        <div class="tbl-wrap" style="margin-top:1rem">
          <table>
            <thead><tr><th>データ</th><th>内容</th><th>閲覧できる主体</th></tr></thead>
            <tbody>
              <tr><td>Account</td><td>顧客ランク・商談・更新日</td><td>営業 / サポート / ERP Agent</td></tr>
              <tr><td>Ticket</td><td>クレーム・問い合わせ（受注番号つき）</td><td>営業 / サポート / ERP Agent</td></tr>
              <tr><td>Contract</td><td>機密契約・違約金条項・最大値引率</td><td><span class="badge red">法務のみ</span></td></tr>
            </tbody>
          </table>
        </div>
        <div class="meta">業務データの API は AI-Sync Bridge の同期専用で、公開経路からは読めません。データは毎日 04:10 に初期状態へ戻ります。架空のサンプルであり、実在の企業とは関係ありません。</div>
      </div>
    </section>
  </main>

<script>
const CRM_DATA = __CRM_PUBLIC_DATA__;
const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));

function switchTab(name) {
  document.querySelectorAll('.tab').forEach((t) => t.classList.toggle('active', t.dataset.tab === name));
  document.querySelectorAll('.pane').forEach((p) => p.classList.toggle('active', p.id === 'pane-' + name));
}
document.querySelectorAll('.tab').forEach((t) => t.addEventListener('click', () => switchTab(t.dataset.tab)));

function askA2A(question) {
  switchTab('a2a');
  $('persona').value = 'support';
  $('q').value = question;
  $('btnAsk').click();
}

// Render KPIs & tables
(function initViews() {
  const accs = CRM_DATA.accounts || [];
  const tcks = CRM_DATA.tickets || [];
  const openCount = tcks.filter((t) => t.Status !== 'Resolved').length;
  $('kpiAcc').textContent = accs.length + ' 社';
  $('kpiTck').textContent = tcks.length + ' 件';
  $('kpiOpen').textContent = openCount + ' 件';
  $('kpiCtr').textContent = (CRM_DATA.contract_count ?? 0) + ' 件 (法務限定)';
  $('ctrCountText').textContent = CRM_DATA.contract_count ?? 0;

  const tierCls = (t) => t === 'VIP' ? 'amber' : t === 'Enterprise' ? '' : 'gray';
  $('accBody').innerHTML = accs.map((a) => `
    <tr>
      <td><code>${esc(a.CustomerId)}</code></td>
      <td><strong>${esc(a.CustomerName)}</strong></td>
      <td><span class="badge ${tierCls(a.Tier)}">${esc(a.Tier)}</span></td>
      <td>${esc(a.AccountOwner)}</td>
      <td>¥${Number(a.AnnualRevenue || 0).toLocaleString('ja-JP')}</td>
      <td>${esc(a.RenewalDate)}</td>
      <td>${esc(a.Notes)}</td>
      <td><button class="sm" data-ask="${esc(a.CustomerName + '(' + a.CustomerId + ')のCRM上の状況と、ERP側の関連受注・出荷状況を教えて')}">A2Aで確認</button></td>
    </tr>`).join('');

  const sevCls = (s) => s === 'High' ? 'red' : s === 'Medium' ? 'amber' : 'gray';
  const stCls = (s) => s === 'Open' ? 'red' : s === 'InProgress' ? 'amber' : 'green';
  $('tckBody').innerHTML = tcks.map((t) => `
    <tr>
      <td><code>${esc(t.Id)}</code></td>
      <td><span class="badge ${sevCls(t.Severity)}">${esc(t.Severity)}</span></td>
      <td><span class="badge ${stCls(t.Status)}">${esc(t.Status)}</span></td>
      <td><strong>${esc(t.CustomerName)}</strong><div class="meta">${esc(t.CustomerId)}</div></td>
      <td><code>${esc(t.OrderId)}</code></td>
      <td><strong>${esc(t.Subject)}</strong><div class="meta">${esc(t.Summary)}</div></td>
      <td>${esc(t.CreatedAt)}</td>
      <td><button class="sm sec" data-ask="${esc(t.CustomerName + '(' + t.CustomerId + ')の注文 ' + t.OrderId + ' のクレーム状況と、ERP側の受注・出荷状況は？')}">ERP状況をA2Aで確認</button></td>
    </tr>`).join('');

  document.querySelectorAll('button[data-ask]').forEach((btn) => {
    btn.addEventListener('click', () => askA2A(btn.dataset.ask));
  });
})();

async function post(url, body) {
  const r = await fetch(url, {method:'POST', headers:{'Content-Type':'application/json'}, body: body ? JSON.stringify(body) : undefined});
  const d = await r.json().catch(() => ({}));
  if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
  return d;
}
const STATUS = {completed:'完了', forbidden:'委譲不可(方針)', 'input-required':'追加情報が必要', error:'エラー', unreachable:'接続不可', failed:'失敗', refused:'相手が拒否', blocked:'遮断中', invited:'招待中(未承認)', rejected:'拒否済'};
document.querySelectorAll('button[data-scn]').forEach((b) => b.addEventListener('click', () => {
  $('q').value = b.dataset.scn;
  $('persona').value = b.dataset.scn.includes('違約金') ? 'legal' : 'support';
  $('btnAsk').click();
}));
$('btnAsk').addEventListener('click', async () => {
  const btn = $('btnAsk'); btn.disabled = true; $('fedErr').textContent = ''; btn.textContent = '回答作成中...';
  try {
    const d = await post('api/a2a-demo/federated-ask', {question:$('q').value, persona:$('persona').value});
    $('fedOut').style.display = 'block';
    const loc = d.local || {}; const erp = (d.peers || []).find((p) => p.peer === 'erp') || {};
    $('crmMeta').textContent = (d.persona && d.persona.label) || '';
    $('crmAns').textContent = loc.answer || '(回答なし)';
    $('crmSub').textContent = `権限で除外 ${loc.acl_filtered ?? 0} 件 · 引用 ${(loc.citations || []).length} 件 · 監査ID ${String(loc.audit_id || '').slice(0, 8)}`;
    $('erpMeta').textContent = STATUS[erp.status] || erp.status || '';
    $('erpMeta').className = 'badge ' + (erp.status === 'completed' ? 'green' : erp.status === 'forbidden' ? 'gray' : 'red');
    $('erpAns').textContent = erp.status === 'forbidden' ? 'この利用者のロールは ERP への委譲が許可されていないため、ERP Agent を呼び出していません。' : (erp.answer || erp.error || '(応答なし)');
    $('erpSub').textContent = erp.status === 'completed' ? `ERP 側で権限により除外 ${erp.acl_filtered ?? 0} 件 · ${erp.latency_ms ?? '-'} ms · ERP 監査ID ${String(erp.audit_id || '').slice(0, 8)}` : '';
    // CRM は物流と直接の信頼関係を持たない。ERP が中継した結果だけがここに来る
    const rl = (erp.relayed || [])[0];
    $('relayBox').style.display = rl ? 'block' : 'none';
    if (rl) {
      $('relayMeta').textContent = (STATUS[rl.status] || rl.status) + (rl.attenuated ? ' · 権限縮退' : '');
      $('relayPath').innerHTML = `経路: <code>${esc([...(rl.path || []), rl.peer].join(' → '))}</code> · 物流側で適用されたロール: <code>${esc((rl.effective_roles || []).join(', ') || '-')}</code>`;
      $('relayAns').textContent = rl.answer || rl.error || '(応答なし)';
      $('relaySub').textContent = rl.status === 'completed' ? `物流側で権限により除外 ${rl.acl_filtered ?? 0} 件（倉庫在庫など ERP 直接の依頼だけに見せる情報）· 物流 監査ID ${String(rl.audit_id || '').slice(0, 8)}` : '';
    }
  } catch (e) { $('fedErr').textContent = 'エラー: ' + e.message; }
  finally { btn.disabled = false; btn.textContent = 'A2A 連携で回答'; }
});
document.querySelectorAll('button[data-dir]').forEach((b) => b.addEventListener('click', async () => {
  b.disabled = true; $('aclErr').textContent = '';
  try {
    const d = await post('api/a2a-demo/acl-check?direction=' + encodeURIComponent(b.dataset.dir));
    $('aclOut').style.display = 'block';
    $('aclBadge').innerHTML = d.leaked ? '<span class="badge red">漏えいを検出</span>' : '<span class="badge green">PASS: 機密は返されていません</span>';
    $('aclQ').textContent = `${d.agent || ''} への質問: ${d.question}`;
    $('aclAns').textContent = d.answer || '(回答なし)';
    $('aclSub').textContent = `タスク状態 ${d.state} · 相手側で権限により除外 ${d.acl_filtered ?? 0} 件 · 監査ID ${String(d.audit_id || '').slice(0, 8)}`;
  } catch (e) { $('aclErr').textContent = 'エラー: ' + e.message; }
  finally { b.disabled = false; }
}));

const GOV_ST = {active:['green','連携中'], invited:['','招待中（相手承認待ち）'], rejected:['red','拒否済'], blocked:['gray','遮断中']};
const INV_ST = {pending:['','承認待ち'], approved:['green','承認済'], rejected:['red','拒否済']};
async function loadCrmGov() {
  try {
    const r = await fetch('api/a2a-demo/governance');
    const d = await r.json();
    if (!r.ok) throw new Error(d.detail || ('HTTP ' + r.status));
    const peers = d.peers || [];
    $('govPeers').innerHTML = '<strong>登録済み Peer（外向き連携先）</strong>' + (peers.length ? peers.map((p) => {
      const [cls, lbl] = GOV_ST[p.status] || ['gray', p.status];
      const btns = [];
      if (p.status === 'active') {
        btns.push(`<button class="sm" data-peer="${esc(p.name)}" data-act="invite">✉️ 招待送信</button>`);
        btns.push(`<button class="sm sec" data-peer="${esc(p.name)}" data-act="block">🚫 遮断</button>`);
      } else if (p.status === 'blocked') {
        btns.push(`<button class="sm" data-peer="${esc(p.name)}" data-act="unblock">🔓 遮断解除</button>`);
      } else if (p.status === 'rejected') {
        btns.push(`<button class="sm" data-peer="${esc(p.name)}" data-act="invite">✉️ 再招待</button>`);
      } else if (p.status === 'invited') {
        btns.push(`<a href="/erp/ai-panel" target="_blank" style="font-size:.82rem">ERP側で承認 ↗</a>`);
      }
      return `<div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem;margin-top:.5rem;padding-top:.5rem;border-top:1px solid #e2e8f0;flex-wrap:wrap">
        <div><strong>${esc(p.name.toUpperCase())} Agent</strong> <span class="badge ${cls}">${esc(lbl)}</span>${p.invite_code ? ` · <code>${esc(p.invite_code)}</code>` : ''}</div>
        <div style="display:flex;gap:.35rem">${btns.join('')}</div>
      </div>`;
    }).join('') : '<div class="meta">Peer なし</div>');

    const invs = d.incoming_invitations || [];
    $('govInbox').innerHTML = '<strong>📥 受信した招待（他システムからのリクエスト）</strong>' + (invs.length ? invs.map((inv) => {
      const [cls, lbl] = INV_ST[inv.status] || ['gray', inv.status];
      const act = inv.status === 'pending'
        ? `<button class="sm" data-inv="${esc(inv.invite_code)}" data-dec="approve">✅ 承認</button>
           <button class="sm warn" data-inv="${esc(inv.invite_code)}" data-dec="reject">✖ 拒否</button>`
        : '';
      return `<div style="display:flex;justify-content:space-between;align-items:center;gap:.5rem;margin-top:.5rem;padding-top:.5rem;border-top:1px solid #e2e8f0;flex-wrap:wrap">
        <div><strong>${esc(inv.from_agent)}</strong> <span class="badge ${cls}">${esc(lbl)}</span><div class="meta">コード: <code>${esc(inv.invite_code)}</code> · ${esc(inv.note || '')}</div></div>
        <div style="display:flex;gap:.35rem">${act}</div>
      </div>`;
    }).join('') : '<div class="meta" style="margin-top:.35rem">受信した招待はありません（ERP側から招待を送るとここに届きます）</div>');

    $('govPeers').querySelectorAll('button[data-act]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try { await post('api/a2a-demo/peers/' + encodeURIComponent(b.dataset.peer) + '/action', {action: b.dataset.act}); await loadCrmGov(); }
      catch (e) { alert('操作失敗: ' + e.message); b.disabled = false; }
    }));
    $('govInbox').querySelectorAll('button[data-inv]').forEach((b) => b.addEventListener('click', async () => {
      b.disabled = true;
      try { await post('api/a2a-demo/invitations/' + encodeURIComponent(b.dataset.inv) + '/respond', {decision: b.dataset.dec}); await loadCrmGov(); }
      catch (e) { alert('応答失敗: ' + e.message); b.disabled = false; }
    }));
  } catch (e) {
    $('govPeers').textContent = '取得エラー: ' + e.message;
  }
}
$('btnGovRefresh').addEventListener('click', loadCrmGov);
$('btnGovReset').addEventListener('click', async () => { await post('api/a2a-demo/reset'); await loadCrmGov(); });
loadCrmGov();
</script>
</body></html>"""


@app.get("/api/health")
def health():
    return {"status": "ok", "system": "legacy-crm"}


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
