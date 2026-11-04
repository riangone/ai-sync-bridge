#!/usr/bin/env python
"""監査ログから検索語・回答本文を消してチェーンを張り直す(元に戻せない)。

API プロセスを止めてから実行する(同時に追記されるとチェーンが分岐するため)。削除した本文が
空き領域に残らないよう、最後に VACUUM する。

  .venv/bin/python scripts/audit_redact.py data/bridge_erp.db --reason "..." --yes
"""
import argparse
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.bridge.audit import AuditLog  # noqa: E402
from app.bridge.store import BridgeStore  # noqa: E402


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("db")
    ap.add_argument("--reason", required=True)
    ap.add_argument("--fields", default="query,answer")
    ap.add_argument("--yes", action="store_true", help="確認なしで実行する")
    args = ap.parse_args()
    if not os.path.exists(args.db):
        sys.exit(f"not found: {args.db}")  # BridgeStore に空の DB を作らせない
    if not args.yes:
        sys.exit("元に戻せない操作です。--yes を付けて実行してください")
    store = BridgeStore(args.db)
    result = AuditLog(store).rebase_redacting(tuple(args.fields.split(",")), args.reason, "ops:audit_redact")
    store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    store.conn.execute("VACUUM")
    store.conn.close()
    print(result)


if __name__ == "__main__":
    main()
