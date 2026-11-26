"""
End-to-end tests for A2A Adapter & ERP <-> CRM cross-system federation.

Run:
    cd ai-api-server && .venv/bin/python tests/test_a2a.py
"""
from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

import httpx
from fastapi import FastAPI

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from app.bridge.acl import Principal
from app.bridge.models import DocAcl
from app.bridge.runtime import BridgeRuntime
from app.bridge.store import DocRecord
from app.bridge import a2a as a2a_mod
from app.routers import a2a as a2a_router


def _fake_vec(text: str) -> list[float]:
    h = sum(ord(c) for c in text)
    return [((h + i * 17) % 97) / 97.0 for i in range(8)]


async def _fake_embed(text: str) -> list[float]:
    return _fake_vec(text)


async def _fake_complete(prompt: str, history=None) -> str:
    # Echo only the grounded <documents> section so tests verify what the LLM actually saw
    start = prompt.find("<documents>")
    end = prompt.find("</documents>")
    docs_part = prompt[start:end] if start != -1 and end != -1 else ""
    return f"[MOCK-LLM] {docs_part} [1]"


def _seed_doc(rt: BridgeRuntime, source: str, entity: str, pk: str, title: str, body: str, acl: DocAcl):
    vec = _fake_vec(f"{title} {body}")
    rt.store.upsert_doc(source, entity, pk, title, body, f"h-{pk}", acl, "ngram-hash-test", vec)
    doc = DocRecord(
        doc_id=f"{source}:{entity}:{pk}",
        source=source,
        entity=entity,
        pk=pk,
        title=title,
        body=body,
        content_hash=f"h-{pk}",
        acl=acl,
        embedder="ngram-hash-test",
        vector=vec,
    )
    rt.retriever.upsert(doc)


def _build_pair(tmp: str):
    erp_profile = {
        "auth": {
            "mode": "api_key",
            "api_keys": [
                {"key": "erp-admin-key", "user_id": "erp_admin", "tenant": "acme", "roles": ["bridge_admin", "sales", "hr", "accounting", "dept:*"]},
                {"key": "crm-to-erp-key", "user_id": "a2a_crm_agent", "tenant": "acme", "roles": ["sales"]},
            ],
        },
        "a2a": {
            "enabled": True,
            "name": "Manufacturing ERP Agent",
            "url": "http://erp.local",
            # 委譲上限: 営業ロールだけが CRM へ委譲できる(人事は不可)
            "peers": [{"name": "crm", "url": "http://crm.local", "api_key": "erp-to-crm-key",
                       "allowed_roles": ["sales"]}],
        },
        "demo": {
            "ask_per_ip_per_hour": 3,
            "personas": [
                {"id": "sales", "label": "営業", "user_id": "sales01", "tenant": "acme", "roles": ["sales"]},
                {"id": "hr", "label": "人事", "user_id": "hr01", "tenant": "acme", "roles": ["hr", "dept:*"]},
            ],
        },
    }
    crm_profile = {
        "auth": {
            "mode": "api_key",
            "api_keys": [
                {"key": "crm-support-key", "user_id": "support01", "tenant": "acme", "roles": ["crm_support", "crm_sales"]},
                {"key": "crm-legal-key", "user_id": "legal01", "tenant": "acme", "roles": ["crm_legal"]},
                {"key": "erp-to-crm-key", "user_id": "a2a_erp_agent", "tenant": "acme", "roles": ["a2a_erp_peer"]},
            ],
        },
        "a2a": {
            "enabled": True,
            "name": "CRM Support & Sales Agent",
            "url": "http://crm.local",
            "peers": [{"name": "erp", "url": "http://erp.local", "api_key": "crm-to-erp-key"}],
        },
    }

    erp_rt = BridgeRuntime(
        erp_profile,
        embed=_fake_embed,
        embedder_id="ngram-hash-test",
        default_store_path=os.path.join(tmp, "erp.db"),
        complete=_fake_complete,
    )
    crm_rt = BridgeRuntime(
        crm_profile,
        embed=_fake_embed,
        embedder_id="ngram-hash-test",
        default_store_path=os.path.join(tmp, "crm.db"),
        complete=_fake_complete,
    )

    # Seed ERP docs
    _seed_doc(
        erp_rt, "legacy_api", "Order", "ORD1001", "ORD1001 山田商事",
        "受注 ORD1001 顧客 山田商事 産業用ポンプ ステータス 製造中 納期 2026-12-05",
        DocAcl(tenant="acme", roles=("sales", "accounting")),
    )
    _seed_doc(
        erp_rt, "legacy_db", "Employee", "E001", "山田太郎 給与",
        "従業員 山田太郎 機密人事評価 給与 850万円",
        DocAcl(tenant="acme", roles=("hr",), depts=("人事部",)),
    )

    # Seed CRM docs
    _seed_doc(
        crm_rt, "legacy_crm_api", "Ticket", "TCK-2026-001", "ORD1001 納期遅延クレーム",
        "山田商事 VIP顧客 受注 ORD1001 納期遅延クレーム 最短補填出荷日を確認要求",
        DocAcl(tenant="acme", roles=("crm_sales", "crm_support", "a2a_erp_peer")),
    )
    _seed_doc(
        crm_rt, "legacy_crm_api", "Contract", "CTR-2026-001", "山田商事 機密違約金契約",
        "山田商事 秘密合意 違約金15% 特別値引10% STRICTLY_CONFIDENTIAL",
        DocAcl(tenant="acme", roles=("crm_legal",)),
    )

    erp_app = FastAPI()
    erp_app.include_router(a2a_router.router)
    erp_app.dependency_overrides[a2a_router.get_bridge] = lambda: erp_rt

    crm_app = FastAPI()
    crm_app.include_router(a2a_router.router)
    crm_app.dependency_overrides[a2a_router.get_bridge] = lambda: crm_rt

    return erp_rt, crm_rt, erp_app, crm_app


async def run_tests():
    with tempfile.TemporaryDirectory() as tmp:
        erp_rt, crm_rt, erp_app, crm_app = _build_pair(tmp)

        async with (
            httpx.AsyncClient(transport=httpx.ASGITransport(app=erp_app), base_url="http://erp.local") as erp_client,
            httpx.AsyncClient(transport=httpx.ASGITransport(app=crm_app), base_url="http://crm.local") as crm_client,
        ):
            # 1. Agent Card discovery
            r = await erp_client.get("/.well-known/agent.json")
            assert r.status_code == 200, r.text
            card = r.json()
            assert card["name"] == "Manufacturing ERP Agent"
            assert card["url"] == "http://erp.local/a2a"

            # 2. Task lifecycle: empty message -> input-required
            r = await erp_client.post(
                "/a2a",
                headers={"Authorization": "Bearer crm-to-erp-key"},
                json={"jsonrpc": "2.0", "id": "1", "method": "tasks/send", "params": {"id": "t-empty", "message": {"role": "user", "parts": []}}},
            )
            assert r.status_code == 200
            assert r.json()["result"]["status"]["state"] == "input-required"

            # 3. CRM peer queries ERP for ORD1001 -> allowed & completed
            r = await erp_client.post(
                "/a2a",
                headers={"Authorization": "Bearer crm-to-erp-key"},
                json={
                    "jsonrpc": "2.0",
                    "id": "2",
                    "method": "tasks/send",
                    "params": {
                        "id": "t-ord",
                        "message": {"role": "user", "parts": [{"type": "text", "text": "山田商事 ORD1001 納期"}]},
                    },
                },
            )
            res = r.json()["result"]
            assert res["status"]["state"] == "completed", res
            assert "ORD1001" in res["status"]["message"]["parts"][0]["text"]

            # 4. tasks/get owner check & tasks/cancel
            r_get = await erp_client.post(
                "/a2a",
                headers={"Authorization": "Bearer crm-to-erp-key"},
                json={"jsonrpc": "2.0", "id": "3", "method": "tasks/get", "params": {"id": "t-ord"}},
            )
            assert r_get.json()["result"]["id"] == "t-ord"

            r_cancel = await erp_client.post(
                "/a2a",
                headers={"Authorization": "Bearer crm-to-erp-key"},
                json={"jsonrpc": "2.0", "id": "4", "method": "tasks/cancel", "params": {"id": "t-ord"}},
            )
            assert r_cancel.json()["result"]["status"]["state"] == "canceled"

            # 5. Bidirectional ACL isolation:
            # 5a. CRM peer tries to read ERP HR Employee record -> MUST NOT leak
            r_hr = await erp_client.post(
                "/a2a",
                headers={"Authorization": "Bearer crm-to-erp-key"},
                json={
                    "jsonrpc": "2.0",
                    "id": "5",
                    "method": "tasks/send",
                    "params": {
                        "id": "t-hr-leak",
                        "message": {"role": "user", "parts": [{"type": "text", "text": "山田太郎 給与 850万円"}]},
                    },
                },
            )
            hr_text = r_hr.json()["result"]["status"]["message"]["parts"][0]["text"]
            assert "850万円" not in hr_text, f"HR secret leaked to CRM peer: {hr_text}"
            assert r_hr.json()["result"]["metadata"]["acl_filtered"] >= 1

            # 5b. ERP peer tries to read CRM Confidential Contract -> MUST NOT leak
            r_ctr = await crm_client.post(
                "/a2a",
                headers={"Authorization": "Bearer erp-to-crm-key"},
                json={
                    "jsonrpc": "2.0",
                    "id": "6",
                    "method": "tasks/send",
                    "params": {
                        "id": "t-ctr-leak",
                        "message": {"role": "user", "parts": [{"type": "text", "text": "山田商事 違約金15% 秘密合意"}]},
                    },
                },
            )
            ctr_text = r_ctr.json()["result"]["status"]["message"]["parts"][0]["text"]
            assert "違約金15%" not in ctr_text, f"Contract secret leaked to ERP peer: {ctr_text}"
            assert r_ctr.json()["result"]["metadata"]["acl_filtered"] >= 1

            # 6. Federated Ask: CRM Support asks about 山田商事 ORD1001 -> local CRM + delegated ERP
            support_principal = Principal(user_id="support01", tenant="acme", roles=("crm_support", "crm_sales"))
            fed = await crm_rt.a2a.federated_ask(
                support_principal,
                "山田商事 ORD1001 納期遅延",
                peers=["erp"],
                client=erp_client,
            )
            assert fed["agent"] == "CRM Support & Sales Agent"
            assert "ORD1001" in fed["local"]["answer"]
            assert fed["peers"]["erp"]["status"] == "completed"
            assert "ORD1001" in fed["peers"]["erp"]["answer"]

            # 7. Audit hash chain integrity on BOTH systems
            assert erp_rt.audit.verify()["ok"] is True
            assert crm_rt.audit.verify()["ok"] is True

            # 8. 匿名主体は鍵付きの A2A 経路を使えない(Agent の Peer キーへの昇格を防ぐ)
            r = await erp_client.post("/a2a", json={"jsonrpc": "2.0", "id": "a", "method": "tasks/get", "params": {"id": "t-ord"}})
            assert r.status_code == 401, r.text
            r = await erp_client.post("/api/a2a/federated-ask", json={"question": "山田商事"})
            assert r.status_code == 401, r.text
            r = await erp_client.get("/api/a2a/peers")
            assert r.status_code == 401, r.text

            # 9. 委譲上限: 人事主体は CRM へ委譲されない(Peer を呼ばずに forbidden)
            erp_rt.a2a.transport = httpx.ASGITransport(app=crm_app)
            crm_tasks_before = len(crm_rt.a2a._tasks)
            hr_principal = Principal(user_id="hr01", tenant="acme", roles=("hr",))
            fed_hr = await erp_rt.a2a.federated_ask(hr_principal, "山田商事 クレーム")
            assert fed_hr["peers"]["crm"]["status"] == "forbidden"
            assert len(crm_rt.a2a._tasks) == crm_tasks_before

            # 10. 公開デモ経路: ペルソナ必須・応答は許可リストのみ・委譲者は監査に残る
            r = await erp_client.get("/api/a2a/demo/peers", params={"persona": "hr"})
            assert r.json()["peers"][0]["allowed"] is False
            r = await erp_client.post("/api/a2a/demo/federated-ask", json={"persona": "nobody", "question": "x"})
            assert r.status_code == 404
            r = await erp_client.post("/api/a2a/demo/federated-ask", json={"persona": "sales", "question": "山田商事 ORD1001 クレーム"})
            assert r.status_code == 200, r.text
            d = r.json()
            assert set(d["local"]) == {"answer", "llm_called", "acl_filtered", "context_count", "audit_id", "citations"}
            peer = d["peers"][0]
            assert peer["peer"] == "crm" and peer["status"] == "completed", peer
            assert "TCK-2026-001" in peer["answer"] or "ORD1001" in peer["answer"]
            assert set(peer) == {"peer", "status", "answer", "acl_filtered", "audit_id", "error", "latency_ms", "relayed"}
            assert [t["kind"] for t in d["trace"]] == ["local", "delegate"], d["trace"]
            received = [e for e in crm_rt.audit.query(limit=50) if e["kind"] == "a2a.task.received"]
            assert received[0]["detail"]["on_behalf_of"] == "sales01", received[0]
            # 公開ペルソナの会話履歴は持ち越さない
            assert not any(k[1] == "sales01" for k in erp_rt.answerer.history._data), "demo session history must be reset"

            # 11. 回数制限: 1回目でローカル1 + CRM1 = 2消費、上限3なので2回目は 429
            r = await erp_client.post("/api/a2a/demo/federated-ask", json={"persona": "sales", "question": "山田商事"})
            assert r.status_code == 429, r.text

            # 12. 到達不能な Peer の内部URLを公開応答に出さない
            erp_rt.a2a.transport = None
            erp_rt.a2a.peers["crm"].url = "http://127.0.0.1:9"
            fed_down = await erp_rt.a2a.federated_ask(Principal(user_id="s", tenant="acme", roles=("sales",)), "山田商事")
            assert fed_down["peers"]["crm"]["status"] == "unreachable"
            assert "127.0.0.1" not in str(fed_down["peers"]["crm"])

            assert erp_rt.audit.verify()["ok"] is True
            assert crm_rt.audit.verify()["ok"] is True

    print("ALL A2A & FEDERATION TESTS PASSED!")


# ---------------------------------------------------------------------------
# 3システム(ERP ハブ + CRM + 物流)の信頼モデル
# ---------------------------------------------------------------------------
def _build_triad(tmp: str):
    erp_profile = {
        "auth": {"mode": "api_key", "api_keys": [
            {"key": "crm-to-erp", "user_id": "a2a_crm_agent", "tenant": "acme", "roles": ["sales"]},
            {"key": "logi-to-erp", "user_id": "a2a_logistics_agent", "tenant": "acme", "roles": ["sales"]},
            {"key": "erp-ops", "user_id": "ops01", "tenant": "acme", "roles": ["sales"]},
        ]},
        "a2a": {"enabled": True, "id": "erp", "name": "Manufacturing ERP Agent", "max_hops": 2, "peers": [
            {"name": "crm", "url": "http://crm.local", "api_key": "erp-to-crm", "allowed_roles": ["sales"],
             "inbound_user_id": "a2a_crm_agent", "relay_to": ["logistics"]},
            {"name": "logistics", "url": "http://logi.local", "api_key": "erp-to-logi",
             "allowed_roles": ["sales", "accounting"], "inbound_user_id": "a2a_logistics_agent"},
        ]},
        "demo": {"ask_per_ip_per_hour": 50, "personas": [
            {"id": "sales", "label": "営業", "user_id": "sales01", "tenant": "acme", "roles": ["sales"]},
            {"id": "manager", "label": "経理", "user_id": "keiri", "tenant": "acme", "roles": ["accounting"]},
        ]},
    }
    crm_profile = {
        "auth": {"mode": "api_key", "api_keys": [
            {"key": "erp-to-crm", "user_id": "a2a_erp_agent", "tenant": "acme", "roles": ["a2a_erp_peer"]},
        ]},
        "a2a": {"enabled": True, "id": "crm", "name": "CRM Support & Sales Agent", "peers": [
            {"name": "erp", "url": "http://erp.local", "api_key": "crm-to-erp", "inbound_user_id": "a2a_erp_agent"},
        ]},
    }
    logi_profile = {
        "auth": {"mode": "api_key", "api_keys": [
            {"key": "erp-to-logi", "user_id": "a2a_erp_agent", "tenant": "acme", "roles": ["a2a_erp_peer"]},
        ]},
        "a2a": {"enabled": True, "id": "logistics", "name": "Logistics & Warehouse Agent", "max_hops": 2, "peers": [
            # ERP が中継してきた依頼(CRM 発)は配送状況だけ見える縮退ロールにする
            {"name": "erp", "url": "http://erp.local", "api_key": "logi-to-erp", "inbound_user_id": "a2a_erp_agent",
             "relay_roles": ["a2a_relay_view"]},
        ]},
    }
    rts = {}
    for name, prof in (("erp", erp_profile), ("crm", crm_profile), ("logi", logi_profile)):
        rts[name] = BridgeRuntime(prof, embed=_fake_embed, embedder_id="ngram-hash-test",
                                  default_store_path=os.path.join(tmp, f"{name}.db"), complete=_fake_complete)
    _seed_doc(rts["erp"], "legacy_api", "Order", "ORD1015", "ORD1015 山田商事",
              "受注 ORD1015 山田商事 ステータス 確認中 納期 2026-08-24", DocAcl(tenant="acme", roles=("sales",)))
    _seed_doc(rts["crm"], "legacy_crm_api", "Ticket", "TCK-1", "ORD1015 納期遅延クレーム",
              "山田商事 ORD1015 納期遅延クレーム VIP", DocAcl(tenant="acme", roles=("a2a_erp_peer",)))
    _seed_doc(rts["logi"], "legacy_logi_api", "Shipment", "SHP-1015", "ORD1015 出荷保留",
              "山田商事 ORD1015 出荷保留 到着予定 2026-12-03 配送状況", DocAcl(tenant="acme", roles=("a2a_erp_peer", "a2a_relay_view")))
    _seed_doc(rts["logi"], "legacy_logi_api", "Stock", "STK-1", "厚木第2倉庫 在庫 ORD1015",
              "山田商事 ORD1015 厚木第2倉庫 ロケーション A-12 引当在庫 12台 倉庫在庫", DocAcl(tenant="acme", roles=("a2a_erp_peer",)))
    apps = {}
    for name, rt in rts.items():
        app = FastAPI()
        app.include_router(a2a_router.router)
        app.dependency_overrides[a2a_router.get_bridge] = (lambda r: (lambda: r))(rt)
        apps[name] = app
    hosts = {"erp.local": apps["erp"], "crm.local": apps["crm"], "logi.local": apps["logi"]}

    class Router(httpx.AsyncBaseTransport):
        """宛先ホストで3つの ASGI アプリに振り分ける(実ネットワークなしで多段委譲を通す)"""
        async def handle_async_request(self, request):
            return await httpx.ASGITransport(app=hosts[request.url.host]).handle_async_request(request)

    for rt in rts.values():
        rt.a2a.transport = Router()
    return rts, apps


async def run_triad_tests():
    with tempfile.TemporaryDirectory() as tmp:
        rts, apps = _build_triad(tmp)
        erp, crm, logi = rts["erp"], rts["crm"], rts["logi"]
        sales = Principal(user_id="sales01", tenant="acme", roles=("sales",))

        def client(name):
            return httpx.AsyncClient(transport=httpx.ASGITransport(app=apps[name]), base_url=f"http://{name}.local")

        async with client("erp") as erp_c, client("logi") as logi_c:
            # T1. CRM → ERP → 物流 の多段委譲: 物流は CRM 発の依頼を縮退ロールで評価し、倉庫在庫は見せない
            fed = await crm.a2a.federated_ask(Principal(user_id="s", tenant="acme", roles=("crm_support",)),
                                              "山田商事 ORD1015 出荷 倉庫在庫 配送状況")
            erp_res = fed["peers"]["erp"]
            assert erp_res["status"] == "completed", erp_res
            relayed = erp_res["metadata"]["relayed"]
            assert [r["peer"] for r in relayed] == ["logistics"], relayed
            r0 = relayed[0]
            assert r0["status"] == "completed" and r0["attenuated"] is True, r0
            assert r0["path"] == ["crm", "erp"] and r0["effective_roles"] == ["a2a_relay_view"], r0
            assert "SHP-1015" in r0["answer"] or "出荷保留" in r0["answer"]
            assert "A-12" not in r0["answer"], "倉庫ロケーションが縮退ロールに漏れた"
            assert r0["acl_filtered"] >= 1
            assert [t["kind"] for t in fed["trace"]] == ["local", "delegate", "relay"]

            # T2. ERP から直接なら(経路長1)倉庫在庫まで見える = 中継者の権限を経由元に貸していない
            fed2 = await erp.a2a.federated_ask(sales, "山田商事 ORD1015 倉庫在庫 ロケーション", peers=["logistics"])
            assert fed2["peers"]["logistics"]["status"] == "completed"
            assert fed2["peers"]["logistics"]["metadata"]["attenuated"] is False
            assert "A-12" in fed2["peers"]["logistics"]["answer"]

            # T3. 経路の自己申告でループ・ホップ超過・中継不可を拒否する
            async def send(c, key, chain):
                return (await c.post("/a2a", headers={"Authorization": f"Bearer {key}"}, json={
                    "jsonrpc": "2.0", "id": "x", "method": "tasks/send",
                    "params": {"message": {"role": "user", "parts": [{"type": "text", "text": "ORD1015"}]},
                               "metadata": {"a2a_chain": chain}}})).json()
            assert "loop" in (await send(logi_c, "erp-to-logi", ["logistics"]))["error"]["message"]
            assert "max hops" in (await send(logi_c, "erp-to-logi", ["crm", "x1"]))["error"]["message"]
            assert "not accepted" in (await send(erp_c, "crm-to-erp", ["logistics"]))["error"]["message"]
            assert (await send(erp_c, "crm-to-erp", ["BAD CHAIN"]))["error"]["message"] == "invalid a2a_chain"
            rejected = [e for e in logi.audit.query(kind="a2a.task.rejected", limit=10)]
            assert any("loop" in e["detail"]["reason"] for e in rejected)

            # T4. 遮断は双方向: ERP が CRM を遮断すると、CRM からの受信も 403
            erp.a2a.set_peer_status("crm", "blocked")
            r = await erp_c.post("/a2a", headers={"Authorization": "Bearer crm-to-erp"},
                                 json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get", "params": {"id": "nope"}})
            assert r.status_code == 403, r.text
            fed_b = await crm.a2a.federated_ask(Principal(user_id="s", tenant="acme", roles=()), "ORD1015")
            assert fed_b["peers"]["erp"]["status"] == "error" and "403" in fed_b["peers"]["erp"]["error"]
            # Peer ではない運用キーには影響しない
            r = await erp_c.post("/a2a", headers={"Authorization": "Bearer erp-ops"},
                                 json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get", "params": {"id": "nope"}})
            assert r.status_code == 200
            erp.a2a.reset_governance_demo()

            # T5. 招待のなりすまし: 本文の差出人ではなくキーで差出人が決まる。Peer 以外のキーは招待できない
            r = await erp_c.post("/a2a/invitations", headers={"Authorization": "Bearer logi-to-erp"},
                                 json={"invite_code": "inv_aaaaaaaa11", "from_agent": "CRM Agent", "from_peer_name": "crm"})
            assert r.status_code == 200 and r.json()["invitation"]["from_peer_name"] == "logistics", r.text
            r = await erp_c.post("/a2a/invitations", headers={"Authorization": "Bearer erp-ops"},
                                 json={"invite_code": "inv_bbbbbbbb22"})
            assert r.status_code == 403

            # T6. 承認コールバックは「招待を送った相手」からだけ。別 Peer がコードを知っていても使えない
            res = await erp.a2a.send_peer_invitation("crm")
            assert res["delivered"] is True and erp.a2a.peers["crm"].status == "invited"
            code = erp.a2a.peers["crm"].invite_code
            assert res["invite_code"] != code  # 公開応答ではマスク
            r = await erp_c.post(f"/a2a/invitations/{code}/decision", headers={"Authorization": "Bearer logi-to-erp"},
                                 json={"decision": "approved"})
            assert r.status_code == 404 and erp.a2a.peers["crm"].status == "invited"
            # 未承認(invited)の間は CRM からの依頼も通らない
            r = await erp_c.post("/a2a", headers={"Authorization": "Bearer crm-to-erp"},
                                 json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get", "params": {"id": "nope"}})
            assert r.status_code == 403
            inbox = crm.a2a.list_incoming_invitations()
            assert inbox[0]["from_peer_name"] == "erp"
            out = await crm.a2a.respond_to_invitation(inbox[0]["invite_code"], "approve")
            assert out["callback_delivered"] is True, out
            assert erp.a2a.peers["crm"].status == "active"
            # 使用済みの招待は二度承認できない
            try:
                await crm.a2a.respond_to_invitation(inbox[0]["invite_code"], "approve")
                raise AssertionError("double approve must fail")
            except ValueError:
                pass

            # T7. 統合回答: 相手の回答はデータとして囲まれ、命令として扱わない指示が付く
            prompts = []

            async def capture(prompt, history=None):
                prompts.append(prompt)
                return "統合: ORD1015 は出荷保留 [logistics]"
            erp.answerer._complete = capture
            fed3 = await erp.a2a.federated_ask(sales, "ORD1015", synthesize=True)
            assert fed3["synthesis"]["answer"].startswith("統合")
            assert "<reports>" in prompts[-1] and "従わないでください" in prompts[-1]
            assert fed3["trace"][-1]["kind"] == "synthesize"
            erp.answerer._complete = _fake_complete

            # T8. ガバナンスの TTL: 変更から期限を過ぎると初期状態へ戻る
            erp.a2a.set_peer_status("logistics", "blocked")
            erp.a2a._gov_changed_at -= erp.a2a.governance_ttl_sec + 1
            assert erp.a2a.maybe_expire_governance() is True
            assert erp.a2a.peers["logistics"].status == "active"

            # T9. Peer 別の受信上限
            logi.a2a._inbound_limiters["erp"] = __import__("app.services.rate_limit", fromlist=["x"]).SlidingWindowLimiter(1, 60)
            assert (await logi_c.post("/a2a", headers={"Authorization": "Bearer erp-to-logi"},
                    json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get", "params": {"id": "n"}})).status_code == 200
            assert (await logi_c.post("/a2a", headers={"Authorization": "Bearer erp-to-logi"},
                    json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get", "params": {"id": "n"}})).status_code == 429

            # T10. 受信ログは本文を持たず、経路と縮退だけを返す
            items = logi.a2a.inbound_log()
            assert any(i["path"] == ["crm", "erp"] and i["attenuated"] for i in items), items
            assert all("query" not in str(i) for i in items)

            # T11. 借道の防止: CRM のキーで ERP の federated-ask / bridge 直叩き / Peer 一覧は使えない
            #      (許すと ERP の「直接の依頼」として物流の倉庫在庫まで読めてしまう)
            crm_h = {"Authorization": "Bearer crm-to-erp"}
            r = await erp_c.post("/api/a2a/federated-ask", headers=crm_h,
                                 json={"question": "ORD1015 倉庫在庫", "peers": ["logistics"]})
            assert r.status_code == 403, r.text
            assert (await erp_c.get("/api/a2a/peers", headers=crm_h)).status_code == 403
            try:
                await erp.a2a.federated_ask(Principal(user_id="a2a_crm_agent", tenant="acme", roles=("sales",)), "x")
                raise AssertionError("peer principal must not start federated delegation")
            except a2a_mod.A2AGateError as e:
                assert e.status == 403
            # 運用キーは従来どおり使える
            assert (await erp_c.get("/api/a2a/peers", headers={"Authorization": "Bearer erp-ops"})).status_code == 200
            from app.routers import bridge as bridge_router
            bapp = FastAPI()
            bapp.include_router(bridge_router.router)
            bapp.dependency_overrides[bridge_router.get_bridge] = lambda: erp
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=bapp), base_url="http://erp.local") as bc:
                r = await bc.post("/api/bridge/search", headers=crm_h, json={"query": "ORD1015"})
                assert r.status_code == 403, r.text
                r = await bc.post("/api/bridge/search", headers={"Authorization": "Bearer erp-ops"}, json={"query": "ORD1015"})
                assert r.status_code == 200, r.text

            # T12. 招待コードの横取り防止: 別の Peer が同じコードで送っても既存の招待を上書きできない
            erp.a2a.reset_governance_demo()
            r = await erp_c.post("/a2a/invitations", headers=crm_h, json={"invite_code": "inv_cccccccc33"})
            assert r.status_code == 200
            r = await erp_c.post("/a2a/invitations", headers={"Authorization": "Bearer logi-to-erp"},
                                 json={"invite_code": "inv_cccccccc33"})
            assert r.status_code == 409, r.text
            assert erp.a2a.incoming_invitations["inv_cccccccc33"].from_peer_name == "crm"

            # T13. 招待が届かなければ既存の連携状態を変えない
            erp.a2a.reset_governance_demo()
            erp.a2a.peers["logistics"].url = "http://unreachable.invalid"
            saved = erp.a2a.transport
            erp.a2a.transport = None
            res = await erp.a2a.send_peer_invitation("logistics")
            erp.a2a.transport = saved
            erp.a2a.peers["logistics"].url = "http://logi.local"
            assert res["delivered"] is False and erp.a2a.peers["logistics"].status == "active", res
            assert erp.a2a.peers["logistics"].invite_code == ""

            # T14. 遮断の TTL は /a2a の入口でも効く(公開ページが開かれていなくても戻る)
            erp.a2a.set_peer_status("crm", "blocked")
            erp.a2a._gov_changed_at -= erp.a2a.governance_ttl_sec + 1
            r = await erp_c.post("/a2a", headers=crm_h,
                                 json={"jsonrpc": "2.0", "id": "1", "method": "tasks/get", "params": {"id": "nope"}})
            assert r.status_code == 200 and erp.a2a.peers["crm"].status == "active", r.text

            for rt in rts.values():
                assert rt.audit.verify()["ok"] is True

    print("ALL 3-SYSTEM TRUST MODEL TESTS PASSED!")


if __name__ == "__main__":
    asyncio.run(run_tests())
    asyncio.run(run_triad_tests())
