#!/bin/bash
# レガシー物流・倉庫管理デモ(127.0.0.1:5030)を起動する。
# この画面プロセスは A2A キーを持たない(Peer 間の通信と ACL 検証は Bridge 5031 の公開デモ経路が行う)。
cd "$(dirname "$0")"
exec ../demo-legacy-system/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 5030
