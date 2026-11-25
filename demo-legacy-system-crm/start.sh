#!/bin/bash
# レガシーCRMデモ(127.0.0.1:5020)を起動する。A2A キーは ops/secrets/a2a.env から読み込む。
cd "$(dirname "$0")"
source ../ops/load-a2a-secrets.sh
exec ../demo-legacy-system/.venv/bin/python -m uvicorn main:app --host 127.0.0.1 --port 5020
