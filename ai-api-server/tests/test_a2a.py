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
            assert set(peer) == {"peer", "status", "answer", "acl_filtered", "audit_id", "error"}
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


if __name__ == "__main__":
    asyncio.run(run_tests())
