"""
BridgeStore: 同期状態の永続化(SQLite 1ファイル)。

  docs    : 1行 = 1文書。内容ハッシュ・ACL・埋め込みベクトル・埋め込みモデルIDを保持。
            → 再起動時はここからインデックスを復元し、再埋め込みしない。
  cursors : (source, entity) ごとの差分取得カーソル(ウォーターマーク/ファイル指紋など)。
  audit   : AuditLog が使う(audit.py)。
"""
from __future__ import annotations

import json
import os
import sqlite3
import threading
import time
from dataclasses import dataclass

from app.bridge.models import DocAcl

_SCHEMA = """
CREATE TABLE IF NOT EXISTS docs (
    doc_id       INTEGER PRIMARY KEY AUTOINCREMENT,
    source       TEXT NOT NULL,
    entity       TEXT NOT NULL,
    pk           TEXT NOT NULL,
    title        TEXT NOT NULL,
    body         TEXT NOT NULL,
    content_hash TEXT NOT NULL,
    acl          TEXT NOT NULL,
    embedder     TEXT NOT NULL,
    vector       TEXT NOT NULL,
    synced_at    REAL NOT NULL,
    UNIQUE (source, entity, pk)
);
CREATE TABLE IF NOT EXISTS cursors (
    source     TEXT NOT NULL,
    entity     TEXT NOT NULL,
    cursor     TEXT,
    updated_at REAL NOT NULL,
    PRIMARY KEY (source, entity)
);
CREATE TABLE IF NOT EXISTS audit (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    ts        REAL NOT NULL,
    kind      TEXT NOT NULL,
    actor     TEXT NOT NULL,
    source    TEXT,
    entity    TEXT,
    ref       TEXT,
    detail    TEXT NOT NULL,
    prev_hash TEXT NOT NULL,
    hash      TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_audit_kind ON audit(kind, ts);
"""


@dataclass
class DocRecord:
    doc_id: int
    source: str
    entity: str
    pk: str
    title: str
    body: str
    content_hash: str
    acl: DocAcl
    embedder: str
    vector: list[float]


class BridgeStore:
    def __init__(self, path: str):
        if path != ":memory:":
            os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        self.conn = sqlite3.connect(path, check_same_thread=False, isolation_level=None)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.executescript(_SCHEMA)
        self.lock = threading.RLock()

    # ---- transactions ----
    def transaction(self):
        store = self

        class _Tx:
            def __enter__(self):
                store.lock.acquire()
                store.conn.execute("BEGIN")
                return store

            def __exit__(self, exc_type, *_):
                try:
                    store.conn.execute("ROLLBACK" if exc_type else "COMMIT")
                finally:
                    store.lock.release()
                return False

        return _Tx()

    # ---- docs ----
    @staticmethod
    def _row_to_doc(r: sqlite3.Row) -> DocRecord:
        return DocRecord(
            r["doc_id"], r["source"], r["entity"], r["pk"], r["title"], r["body"], r["content_hash"],
            DocAcl.from_json(json.loads(r["acl"])), r["embedder"], json.loads(r["vector"]),
        )

    def all_docs(self) -> list[DocRecord]:
        with self.lock:
            return [self._row_to_doc(r) for r in self.conn.execute("SELECT * FROM docs")]

    def doc_hashes(self, source: str, entity: str) -> dict[str, tuple[int, str, str]]:
        """pk -> (doc_id, content_hash, embedder)"""
        with self.lock:
            rows = self.conn.execute(
                "SELECT pk, doc_id, content_hash, embedder FROM docs WHERE source=? AND entity=?", (source, entity)
            )
            return {r["pk"]: (r["doc_id"], r["content_hash"], r["embedder"]) for r in rows}

    def upsert_doc(self, source, entity, pk, title, body, chash, acl: DocAcl, embedder, vector) -> int:
        self.conn.execute(
            """INSERT INTO docs(source, entity, pk, title, body, content_hash, acl, embedder, vector, synced_at)
               VALUES (?,?,?,?,?,?,?,?,?,?)
               ON CONFLICT(source, entity, pk) DO UPDATE SET
                 title=excluded.title, body=excluded.body, content_hash=excluded.content_hash,
                 acl=excluded.acl, embedder=excluded.embedder, vector=excluded.vector, synced_at=excluded.synced_at""",
            (source, entity, pk, title, body, chash, json.dumps(acl.to_json(), ensure_ascii=False),
             embedder, json.dumps(vector), time.time()),
        )
        return self.conn.execute(
            "SELECT doc_id FROM docs WHERE source=? AND entity=? AND pk=?", (source, entity, pk)
        ).fetchone()[0]

    def delete_doc(self, doc_id: int) -> None:
        self.conn.execute("DELETE FROM docs WHERE doc_id=?", (doc_id,))

    # ---- embedder migration(埋め込みモデル切り替え後の追いつき)----
    def update_vector(self, doc_id: int, embedder: str, vector: list[float]) -> None:
        with self.lock:
            self.conn.execute("UPDATE docs SET embedder=?, vector=?, synced_at=? WHERE doc_id=?",
                              (embedder, json.dumps(vector), time.time(), doc_id))

    def get_doc(self, doc_id: int) -> DocRecord | None:
        with self.lock:
            r = self.conn.execute("SELECT * FROM docs WHERE doc_id=?", (doc_id,)).fetchone()
        return self._row_to_doc(r) if r else None

    def docs_with_other_embedder(self, embedder: str) -> list[DocRecord]:
        with self.lock:
            rows = self.conn.execute("SELECT * FROM docs WHERE embedder != ? ORDER BY doc_id",
                                     (embedder,)).fetchall()
        return [self._row_to_doc(r) for r in rows]

    def count_other_embedder(self, embedder: str) -> int:
        with self.lock:
            return self.conn.execute("SELECT COUNT(*) FROM docs WHERE embedder != ?", (embedder,)).fetchone()[0]

    # ---- stats(運用の実感: /status に出す)----
    def size_bytes(self) -> int | None:
        """DB ファイル本体のサイズ。WAL 分は含まない(別ファイルにあり、チェックポイントで吸収される)。"""
        path = self.conn.execute("PRAGMA database_list").fetchone()[2]
        try:
            return os.path.getsize(path) if path else None
        except OSError:
            return None

    def vector_bytes(self) -> int | None:
        """埋め込みベクトル列(text の JSON)の合計バイト数。DB 肥大化の主因を量る。"""
        with self.lock:
            r = self.conn.execute("SELECT SUM(LENGTH(vector)) FROM docs").fetchone()[0]
        return int(r or 0)

    def count_docs(self) -> dict[str, int]:
        with self.lock:
            rows = self.conn.execute("SELECT source || '/' || entity AS k, COUNT(*) AS n FROM docs GROUP BY k")
            return {r["k"]: r["n"] for r in rows}

    # ---- cursors ----
    def get_cursor(self, source: str, entity: str) -> dict | None:
        with self.lock:
            r = self.conn.execute("SELECT cursor FROM cursors WHERE source=? AND entity=?", (source, entity)).fetchone()
        return json.loads(r["cursor"]) if r and r["cursor"] else None

    def set_cursor(self, source: str, entity: str, cursor: dict | None) -> None:
        self.conn.execute(
            """INSERT INTO cursors(source, entity, cursor, updated_at) VALUES (?,?,?,?)
               ON CONFLICT(source, entity) DO UPDATE SET cursor=excluded.cursor, updated_at=excluded.updated_at""",
            (source, entity, json.dumps(cursor, ensure_ascii=False) if cursor is not None else None, time.time()),
        )
