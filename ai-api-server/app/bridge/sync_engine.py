"""
SyncEngine: Connector の取得結果を「行単位の内容ハッシュ」で差分判定し、
変更行だけを埋め込み → BridgeStore 永続化 → インデックス更新 → 監査記録する。

不変条件:
  - 内容ハッシュと埋め込みモデルIDが前回と同じ行は再埋め込みしない(AIコスト/時間の削減)
  - snapshot の場合のみ「rows に無い既存文書」を削除する(差分取得で削除扱いしない)
  - 1エンティティの反映は1トランザクション。埋め込みはトランザクション外で先に済ませる
    (AI呼び出し中にDBロックを握らない)。途中で失敗したらカーソルも進めない。
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field

from app.bridge.audit import AuditLog
from app.bridge.connectors import Connector
from app.bridge.models import EntitySpec, content_hash
from app.bridge.store import BridgeStore


@dataclass
class EntitySyncStats:
    source: str
    entity: str
    fetched: int = 0
    upserted: int = 0
    unchanged: int = 0
    deleted: int = 0
    skipped_invalid: int = 0
    source_unchanged: bool = False
    error: str | None = None
    elapsed_ms: int = 0
    upserted_doc_ids: list[int] = field(default_factory=list, repr=False)
    deleted_doc_ids: list[int] = field(default_factory=list, repr=False)

    def summary(self) -> dict:
        d = dict(self.__dict__)
        d.pop("upserted_doc_ids")
        d.pop("deleted_doc_ids")
        return d


SPEC_CURSOR_KEY = "_spec"


class SyncEngine:
    def __init__(self, store: BridgeStore, audit: AuditLog, embed, embedder_id: str):
        self.store = store
        self.audit = audit
        self._embed = embed           # async (text) -> list[float]
        self.embedder_id = embedder_id

    async def sync_entity(self, conn: Connector, spec: EntitySpec, actor: str) -> EntitySyncStats:
        st = EntitySyncStats(conn.name, spec.name)
        t0 = time.monotonic()
        try:
            cursor = self.store.get_cursor(conn.name, spec.name)
            # ACL や本文の設定を変えたら、ソースが未変更でも読み直す(古い権限を残さない)
            spec_fp = spec.fingerprint()
            if cursor and cursor.get(SPEC_CURSOR_KEY) != spec_fp:
                cursor = None
            result = await conn.fetch(spec, cursor)
            st.fetched = len(result.rows)
            if result.unchanged:
                st.source_unchanged = True
                return st

            existing = self.store.doc_hashes(conn.name, spec.name)
            seen: set[str] = set()
            pending = []  # (pk, title, body, hash, acl, vector)
            for row in result.rows:
                try:
                    pk = spec.pk_of(row)
                except ValueError:
                    st.skipped_invalid += 1
                    continue
                seen.add(pk)
                body = spec.render_text(row)
                title = spec.title_of(row)
                acl = spec.acl_of(row)
                h = content_hash(body, title, acl)
                prev = existing.get(pk)
                if prev and prev[1] == h and prev[2] == self.embedder_id:
                    st.unchanged += 1
                    continue
                vec = await self._embed(f"{title} {body}")
                pending.append((pk, title, body, h, acl, vec, prev[1] if prev else None))

            to_delete = set(result.deleted)
            if result.snapshot:
                to_delete |= set(existing) - seen

            with self.store.transaction():
                for pk, title, body, h, acl, vec, prev_hash in pending:
                    doc_id = self.store.upsert_doc(conn.name, spec.name, pk, title, body, h, acl, self.embedder_id, vec)
                    st.upserted_doc_ids.append(doc_id)
                    self.audit.append(
                        "sync.upsert", actor, source=conn.name, entity=spec.name, ref=pk,
                        detail={"doc_id": doc_id, "hash": h, "prev_hash": prev_hash,
                                "embedder": self.embedder_id, "acl": acl.to_json()},
                    )
                for pk in sorted(to_delete):
                    if pk not in existing:
                        continue
                    doc_id, h, _ = existing[pk]
                    self.store.delete_doc(doc_id)
                    st.deleted_doc_ids.append(doc_id)
                    self.audit.append("sync.delete", actor, source=conn.name, entity=spec.name, ref=pk,
                                      detail={"doc_id": doc_id, "last_hash": h})
                self.store.set_cursor(conn.name, spec.name, {**(result.cursor or {}), SPEC_CURSOR_KEY: spec_fp})
            st.upserted = len(st.upserted_doc_ids)
            st.deleted = len(st.deleted_doc_ids)
        except Exception as e:  # 1エンティティの失敗で他エンティティの同期を止めない
            st.error = f"{type(e).__name__}: {e}"
            st.upserted_doc_ids.clear()
            st.deleted_doc_ids.clear()
        finally:
            st.elapsed_ms = int((time.monotonic() - t0) * 1000)
        return st
