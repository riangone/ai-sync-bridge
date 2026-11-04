"""
公開デモ用ゲートウェイ: ブラウザに API キーを置かず、サーバー側で主体(ペルソナ)を切り替える。

/api/bridge/* の本来の API は実キーを持つ呼び出し元向けのまま残し、公開ページからは
/api/bridge/demo/* だけを使う(routers/bridge_demo.py)。profile の demo 節が無い導入先では
すべて 404 になる。

不変条件:
  1. ペルソナは管理者ロール(bridge_admin)を持てない。設定されていれば起動時に失敗する。
  2. 応答は許可リストの項目だけを返す。監査の検索語・回答本文、同期エラー(接続先やパスを
     含み得る)、プロファイルのパスは公開経路に出さない。
  3. ペルソナは全訪問者で共有されるため、会話履歴を持ち越さない。リクエストごとに
     推測できないセッションを発行し、回答後に破棄する(訪問者間の質問の漏洩防止)。
  4. LLM 消費と監査の増加を抑えるため、IP ごとの回数制限と同期のクールダウンを設ける。

    demo:
      ask_per_ip_per_hour: 40      # 比較1回で主体の数だけ消費する
      read_per_ip_per_minute: 60
      sync_cooldown_sec: 60
      personas:
        - {id: sales, label: 営業担当, note: 営業部, user_id: sales01, tenant: acme, roles: [sales], depts: [営業部]}
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass

from app.bridge.acl import ADMIN_ROLE, Principal
from app.services.rate_limit import SlidingWindowLimiter, client_ip  # noqa: F401 (client_ip は公開名)

@dataclass(frozen=True)
class Persona:
    id: str
    label: str
    note: str
    principal: Principal


class DemoGateway:
    def __init__(self, cfg: dict):
        self.personas: dict[str, Persona] = {}
        for p in cfg.get("personas") or []:
            roles = tuple(p.get("roles") or ())
            if ADMIN_ROLE in roles:
                raise ValueError(f"demo persona に {ADMIN_ROLE} は付与できません: {p.get('id')}")
            if p["id"] in self.personas:
                raise ValueError(f"demo persona の id が重複しています: {p['id']}")
            self.personas[p["id"]] = Persona(
                id=p["id"], label=p.get("label", p["id"]), note=p.get("note", ""),
                principal=Principal(user_id=str(p["user_id"]), tenant=p.get("tenant"),
                                    roles=roles, depts=tuple(p.get("depts") or ())),
            )
        self.ask_limiter = SlidingWindowLimiter(int(cfg.get("ask_per_ip_per_hour", 40)), 3600)
        self.read_limiter = SlidingWindowLimiter(int(cfg.get("read_per_ip_per_minute", 60)), 60)
        self.sync_cooldown = float(cfg.get("sync_cooldown_sec", 60))
        self._last_sync_at: float | None = None
        self._last_sync: dict | None = None
        self._sync_lock = threading.Lock()

    def claim_sync(self) -> dict | None:
        """同期を始めてよければ None、クールダウン中なら前回の結果(無ければ空の結果)を返す。"""
        now = time.monotonic()
        with self._sync_lock:
            if self._last_sync_at is not None and now - self._last_sync_at < self.sync_cooldown:
                return {**(self._last_sync or public_sync({})), "cached": True}
            self._last_sync_at = now
            return None

    def store_sync(self, result: dict) -> None:
        with self._sync_lock:
            self._last_sync = result


def public_search(res: dict) -> dict:
    return {
        "strategy": res["strategy"],
        "acl_filtered": res["acl_filtered"],
        "audit_id": res["audit_id"],
        "results": [{"entity": r["entity"], "pk": r["pk"], "title": r["title"]} for r in res["results"]],
    }


def public_answer(res: dict) -> dict:
    return {
        "answer": res["answer"],
        "llm_called": res["llm_called"],
        "acl_filtered": res["acl_filtered"],
        "context_count": len(res["context"]),
        "audit_id": res["audit_id"],
        "citations": [{"n": c["n"], "entity": c["entity"], "pk": c["pk"], "title": c["title"]}
                      for c in res["citations"]],
    }


def public_sync(res: dict) -> dict:
    return {
        "elapsed_ms": res.get("elapsed_ms", 0),
        "upserted": res.get("upserted", 0),
        "unchanged": res.get("unchanged", 0),
        "deleted": res.get("deleted", 0),
        "cached": False,
        "entities": [
            {"source": e.get("source"), "entity": e.get("entity"), "fetched": e.get("fetched"),
             "upserted": e.get("upserted"), "unchanged": e.get("unchanged"), "deleted": e.get("deleted"),
             "source_unchanged": bool(e.get("source_unchanged")), "failed": bool(e.get("error"))}
            for e in res.get("entities", [])
        ],
    }


def _public_audit_counts(kind: str, d: dict) -> dict:
    if kind == "retrieval":
        return {"returned": len(d.get("returned") or []), "acl_filtered": d.get("acl_filtered")}
    if kind == "rag.answer":
        return {"context": len(d.get("context") or []), "cited": len(d.get("cited") or []),
                "llm_called": bool(d.get("llm_called"))}
    if kind == "sync.run":
        return {"upserted": d.get("upserted"), "unchanged": d.get("unchanged"), "deleted": d.get("deleted")}
    return {}


def public_audit_item(it: dict) -> dict:
    return {
        "seq": it["seq"], "ts": it["ts"], "kind": it["kind"], "actor": it["actor"], "hash": it["hash"],
        "source": it["source"], "entity": it["entity"], "ref": it["ref"],
        "counts": _public_audit_counts(it["kind"], it.get("detail") or {}),
    }


def public_verify(res: dict) -> dict:
    return {k: res[k] for k in ("ok", "checked", "head", "broken_at_seq") if k in res}
