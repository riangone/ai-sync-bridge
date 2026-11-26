#!/bin/bash
# レガシーCRMデモ(127.0.0.1:5020)を起動する。
# この画面プロセスは A2A キーを持たない(ACL 検証も各 Bridge の公開デモ経路 /api/a2a/demo/acl-probe が行う)。
cd "$(dirname "$0")"
exec ../demo-legacy-system/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 5020
