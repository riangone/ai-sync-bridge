"""
AuditLog: 改ざん検知可能な追記専用監査ログ(ハッシュチェーン)。

各レコードの hash = sha256(prev_hash + 正規化JSON(本体))。途中の1件でも書き換え/削除
されると verify() で検出できる。記録対象:
  sync.upsert / sync.delete : どの行(source/entity/pk)を、どの内容ハッシュで取り込んだか
  sync.run                  : 同期実行のサマリ(件数・所要時間・エラー)
  retrieval                 : 誰が・何を検索し・どの文書(内容ハッシュ付き)がAIに渡ったか、
                              ACLで何件除外されたか
"""
from __future__ import annotations

import hashlib
import json
import time

from app.bridge.store import BridgeStore

GENESIS = "0" * 64


def _digest(prev_hash: str, body: dict) -> str:
    canon = json.dumps(body, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256((prev_hash + canon).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, store: BridgeStore):
        self.store = store

    def append(self, kind: str, actor: str, *, source=None, entity=None, ref=None, detail: dict | None = None) -> str:
        """呼び出し側のトランザクション内でも単独でも使える(RLockで直列化)。"""
        with self.store.lock:
            row = self.store.conn.execute("SELECT hash FROM audit ORDER BY seq DESC LIMIT 1").fetchone()
            prev = row["hash"] if row else GENESIS
            body = {
                "ts": round(time.time(), 6), "kind": kind, "actor": actor,
                "source": source, "entity": entity, "ref": ref, "detail": detail or {},
            }
            h = _digest(prev, body)
            self.store.conn.execute(
                "INSERT INTO audit(ts, kind, actor, source, entity, ref, detail, prev_hash, hash) VALUES (?,?,?,?,?,?,?,?,?)",
                (body["ts"], kind, actor, source, entity, ref,
                 json.dumps(body["detail"], ensure_ascii=False, sort_keys=True), prev, h),
            )
            return h

    def query(self, kind: str | None = None, limit: int = 100, since_seq: int = 0) -> list[dict]:
        sql = "SELECT * FROM audit WHERE seq > ?"
        args: list = [since_seq]
        if kind:
            sql += " AND kind LIKE ?"
            args.append(kind.replace("*", "%"))
        sql += " ORDER BY seq DESC LIMIT ?"
        args.append(max(1, min(limit, 1000)))
        with self.store.lock:
            rows = self.store.conn.execute(sql, args).fetchall()
        return [{**dict(r), "detail": json.loads(r["detail"])} for r in rows]

    def verify(self) -> dict:
        prev = GENESIS
        n = 0
        with self.store.lock:
            for r in self.store.conn.execute("SELECT * FROM audit ORDER BY seq"):
                body = {
                    "ts": r["ts"], "kind": r["kind"], "actor": r["actor"], "source": r["source"],
                    "entity": r["entity"], "ref": r["ref"], "detail": json.loads(r["detail"]),
                }
                if r["prev_hash"] != prev or _digest(prev, body) != r["hash"]:
                    return {"ok": False, "checked": n, "broken_at_seq": r["seq"]}
                prev = r["hash"]
                n += 1
        return {"ok": True, "checked": n, "head": prev}

    def rebase_redacting(self, fields: tuple[str, ...], reason: str, actor: str) -> dict:
        """detail から fields を消してチェーンを先頭から張り直す。

        ハッシュは本文に依存するので、本文を消すと以降の全ハッシュが変わる。これは改ざんと同じ
        操作なので、旧チェーンの先頭ハッシュと理由を audit.rebase として残す(旧ハッシュを控えて
        いた第三者には差し替えが分かる)。rag.answer から retrieval への参照も新ハッシュへ付け替える。
        削除した本文は戻せない。途中で検証に失敗したらロールバックする。
        """
        conn = self.store.conn
        with self.store.lock:
            before = self.verify()
            if not before["ok"]:
                raise ValueError(f"チェーンが既に壊れているため張り直しません: {before}")
            remapped: dict[str, str] = {}
            prev = GENESIS
            redacted = 0
            conn.commit()
            conn.execute("BEGIN IMMEDIATE")
            try:
                for r in conn.execute("SELECT * FROM audit ORDER BY seq").fetchall():
                    detail = json.loads(r["detail"])
                    if any(f in detail for f in fields):
                        redacted += 1
                        detail = {k: v for k, v in detail.items() if k not in fields}
                    if detail.get("retrieval_audit_id") in remapped:
                        detail["retrieval_audit_id"] = remapped[detail["retrieval_audit_id"]]
                    body = {"ts": r["ts"], "kind": r["kind"], "actor": r["actor"], "source": r["source"],
                            "entity": r["entity"], "ref": r["ref"], "detail": detail}
                    h = _digest(prev, body)
                    conn.execute("UPDATE audit SET detail=?, prev_hash=?, hash=? WHERE seq=?",
                                 (json.dumps(detail, ensure_ascii=False, sort_keys=True), prev, h, r["seq"]))
                    remapped[r["hash"]] = h
                    prev = h
                self.append("audit.rebase", actor, detail={
                    "old_head": before.get("head"), "old_count": before["checked"],
                    "redacted_fields": list(fields), "redacted_records": redacted, "reason": reason,
                })
                after = self.verify()
                if not after["ok"] or after["checked"] != before["checked"] + 1:
                    raise ValueError(f"張り直し後の検証に失敗しました: {after}")
                conn.commit()
            except Exception:
                conn.rollback()
                raise
        return {"redacted_records": redacted, "old_head": before.get("head"), **after}
