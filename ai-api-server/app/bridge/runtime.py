"""
BridgeRuntime (Singleton): プロファイル(YAML)から Connector/EntitySpec/認証設定を組み立て、
同期・検索・監査の入口を提供する。

プロファイルは導入先ごとの設定であり、コア(このパッケージ)には業種知識を一切書かない。
既定の置き場所は各デモの aisb_profile/bridge.yaml(環境変数 AISB_BRIDGE_PROFILE で指定)。

    store:   {path: ...}                         # 省略時 data/bridge_<instance>.db
    auth:    {mode: api_key, api_keys: [...]}    # acl.py 参照
    audit:   {store_query_text: true,            # 検索クエリ本文を監査ログに残すか(既定 true)
              store_answer_text: true}           # AI回答本文を監査ログに残すか(既定 true)
    answer:  {top_k: 5, max_doc_chars: 1200}     # /api/bridge/ask(権限付きRAG)の既定値
    sync:    {interval_sec: 0}                   # >0 で起動時から定期同期
    sources:
      - name: legacy_erp
        type: http_list | sql | file
        config: {...}                            # コネクタ設定(${ENV:-default} 展開可)
        entities:
          - name: Customer
            pk: Id
            title: Name
            text: [Name, Industry, Notes]
            acl: {tenant: acme, depts: $Department, roles: [sales]}
            options: {...}                       # コネクタ固有
"""
from __future__ import annotations

import asyncio
import hashlib
import os
import re
import time
from dataclasses import dataclass

import yaml

from app.bridge.acl import Principal, PrincipalResolver
from app.bridge.answerer import GroundedAnswerer
from app.bridge.audit import AuditLog
from app.bridge.connectors import Connector, build_connector
from app.bridge.models import EntitySpec
from app.bridge.retriever import Retriever
from app.bridge.store import BridgeStore
from app.bridge.sync_engine import EntitySyncStats, SyncEngine

_ENV_PAT = re.compile(r"\$\{([A-Z0-9_]+)(?::-([^}]*))?\}")


def _expand_env(obj):
    if isinstance(obj, str):
        return _ENV_PAT.sub(lambda m: os.environ.get(m.group(1), m.group(2) or ""), obj)
    if isinstance(obj, list):
        return [_expand_env(x) for x in obj]
    if isinstance(obj, dict):
        return {k: _expand_env(v) for k, v in obj.items()}
    return obj


@dataclass
class Source:
    connector: Connector
    entities: list[EntitySpec]


def _entity_from_cfg(e: dict) -> EntitySpec:
    text = e.get("text") or []
    if isinstance(text, str):
        text = [text]
    if not e.get("name") or not e.get("pk") or not text:
        raise ValueError(f"entity 定義には name/pk/text が必須です: {e}")
    return EntitySpec(
        name=e["name"], pk=e["pk"], text_fields=tuple(text), title_field=e.get("title"),
        acl=dict(e.get("acl") or {}), options=dict(e.get("options") or {}),
    )


class BridgeRuntime:
    def __init__(self, profile: dict, *, embed, embedder_id: str, default_store_path: str,
                 vector_backend: str = "brute-force", profile_path: str | None = None,
                 complete=None):
        profile = _expand_env(profile or {})
        self.profile_path = profile_path
        self.store = BridgeStore((profile.get("store") or {}).get("path") or default_store_path)
        self.audit = AuditLog(self.store)
        self.resolver = PrincipalResolver(profile.get("auth"))
        acfg = profile.get("audit") or {}
        self.store_query_text = bool(acfg.get("store_query_text", True))
        anscfg = profile.get("answer") or {}
        self.answer_top_k = int(anscfg.get("top_k", 5))
        self.answerer = GroundedAnswerer(
            complete,
            max_doc_chars=int(anscfg.get("max_doc_chars", 1200)),
            store_answer_text=bool(acfg.get("store_answer_text", True)),
        )
        self.sync_interval = float((profile.get("sync") or {}).get("interval_sec", 0) or 0)
        self._embed = embed
        self.engine = SyncEngine(self.store, self.audit, embed, embedder_id)
        rcfg = profile.get("retrieval") or {}
        self.retriever = Retriever(
            vector_backend,
            hybrid=bool(rcfg.get("hybrid", True)),
            vector_weight=float(rcfg.get("vector_weight", 1.0)),
            lexical_weight=float(rcfg.get("lexical_weight", 1.0)),
        )
        self.sources: dict[str, Source] = {}
        for s in profile.get("sources") or []:
            conn = build_connector(s["name"], s["type"], s.get("config") or {})
            self.sources[s["name"]] = Source(conn, [_entity_from_cfg(e) for e in s.get("entities") or []])
        self.retriever.load(self.store.all_docs())
        self._sync_lock = asyncio.Lock()
        self.last_sync: dict | None = None

    @classmethod
    def from_file(cls, path: str | None, **kw) -> "BridgeRuntime":
        profile = {}
        if path:
            with open(path, encoding="utf-8") as f:
                profile = yaml.safe_load(f) or {}
        return cls(profile, profile_path=path, **kw)

    # ---------------- sync ----------------
    async def sync(self, actor: str, source: str | None = None, entity: str | None = None) -> dict:
        if source and source not in self.sources:
            raise KeyError(f"unknown source: {source}")
        async with self._sync_lock:  # 同時同期でカーソル/インデックスが競合しないよう直列化
            t0 = time.monotonic()
            results: list[EntitySyncStats] = []
            for name, src in self.sources.items():
                if source and name != source:
                    continue
                for spec in src.entities:
                    if entity and spec.name != entity:
                        continue
                    st = await self.engine.sync_entity(src.connector, spec, actor)
                    results.append(st)
                    self._apply_to_index(st)
            summary = {
                "elapsed_ms": int((time.monotonic() - t0) * 1000),
                "upserted": sum(r.upserted for r in results),
                "deleted": sum(r.deleted for r in results),
                "unchanged": sum(r.unchanged for r in results),
                "errors": sum(1 for r in results if r.error),
                "entities": [r.summary() for r in results],
            }
            self.audit.append("sync.run", actor, source=source, entity=entity,
                              detail={k: v for k, v in summary.items() if k != "entities"}
                              | {"failed": [f"{r.source}/{r.entity}: {r.error}" for r in results if r.error]})
            self.last_sync = {"at": time.time(), **summary}
            return summary

    def _apply_to_index(self, st: EntitySyncStats) -> None:
        for doc_id in st.deleted_doc_ids:
            self.retriever.remove(doc_id)
        if st.upserted_doc_ids:
            ids = set(st.upserted_doc_ids)
            for d in self.store.all_docs():  # 件数が多い導入先では doc_id 指定の取得に置き換える
                if d.doc_id in ids:
                    self.retriever.upsert(d)

    async def run_periodic(self) -> None:
        while True:
            await asyncio.sleep(self.sync_interval)
            try:
                await self.sync(actor="system:scheduler")
            except Exception:
                pass  # 個別エラーは sync.run 監査に残る

    # ---------------- search ----------------
    async def _retrieve(self, principal: Principal, query: str, top_k: int,
                        entities: list[str] | None, purpose: str):
        """ACL 前置フィルタ付き検索 + retrieval 監査。返す文書はすべて principal が閲覧可能。"""
        qvec = await self._embed(query)
        hits, filtered, strategy = self.retriever.search(principal, qvec, top_k, set(entities) if entities else None, query=query)
        detail = {
            "query_sha256": hashlib.sha256(query.encode("utf-8")).hexdigest(),
            "top_k": top_k, "entities": entities, "strategy": strategy, "purpose": purpose,
            "acl_filtered": filtered,
            "returned": [{"ref": f"{d.source}/{d.entity}/{d.pk}", "hash": d.content_hash} for d, _ in hits],
            "principal": principal.to_json(),
        }
        if self.store_query_text:
            detail["query"] = query
        audit_hash = self.audit.append("retrieval", principal.user_id, detail=detail)
        return hits, filtered, strategy, audit_hash

    async def search(self, principal: Principal, query: str, top_k: int = 5,
                     entities: list[str] | None = None) -> dict:
        hits, filtered, strategy, audit_hash = await self._retrieve(principal, query, top_k, entities, "search")
        results = [
            {"source": d.source, "entity": d.entity, "pk": d.pk, "title": d.title,
             "snippet": d.body[:200], "score": round(s, 4), "content_hash": d.content_hash}
            for d, s in hits
        ]
        return {"query": query, "strategy": strategy, "backend": self.retriever.backend_name,
                "acl_filtered": filtered, "audit_id": audit_hash, "results": results}

    # ---------------- grounded answer (RAG) ----------------
    async def ask(self, principal: Principal, question: str, session_id: str = "default",
                  top_k: int | None = None, entities: list[str] | None = None) -> dict:
        """権限付き検索 → 閲覧可能文書だけを根拠に回答 → rag.answer 監査。"""
        if not self.answerer.enabled:
            raise RuntimeError("LLM が設定されていないため回答生成は利用できません")
        hits, filtered, strategy, retrieval_id = await self._retrieve(
            principal, question, top_k or self.answer_top_k, entities, "answer")
        res = await self.answerer.answer(
            principal=principal, question=question, session_id=session_id,
            docs=[d for d, _ in hits], retrieval_audit_id=retrieval_id,
            audit=self.audit, store_query_text=self.store_query_text)
        return {"question": question, "session_id": session_id, "strategy": strategy,
                "acl_filtered": filtered, **res}

    def reset_conversation(self, principal: Principal, session_id: str) -> None:
        self.answerer.history.clear(self.answerer.history.key(principal, session_id))

    # ---------------- status ----------------
    def status(self) -> dict:
        return {
            "profile": self.profile_path,
            "auth_mode": self.resolver.mode,
            "embedder": self.engine.embedder_id,
            "answer_enabled": self.answerer.enabled,
            "vector_backend": self.retriever.backend_name,
            "indexed_docs": self.retriever.size(),
            "docs_by_entity": self.store.count_docs(),
            "sync_interval_sec": self.sync_interval,
            "last_sync": {k: v for k, v in (self.last_sync or {}).items() if k != "entities"} or None,
            "sources": [
                {**src.connector.describe(), "entities": [e.name for e in src.entities],
                 "cursors": {e.name: self.store.get_cursor(name, e.name) for e in src.entities}}
                for name, src in self.sources.items()
            ],
        }
