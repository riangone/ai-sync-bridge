#!/bin/bash
# ai-api-server を「ERP版(demo-legacy-system, port 5010)向けインスタンス」として起動する。
# AISB_INSTANCE=erp が無いと既定値"erp"にフォールバックするため実害は無いが、
# start-dealer.sh と対で明示しておくことで「envを設定し忘れて2インスタンスが
# 同じSQLiteファイルを取り合う」事故を構造的に防ぐ。
cd "$(dirname "$0")"
export AISB_INSTANCE=erp
export AISB_LEGACY_BASE_URL="${AISB_LEGACY_BASE_URL:-http://localhost:5010}"
export AISB_AI_PROVIDER="${AISB_AI_PROVIDER:-opencode}"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 5011
