#!/bin/bash
# ai-api-server を「不動産仲介版(demo-legacy-system-realestate, port 5030)向け
# インスタンス」として起動する。AISB_INSTANCE=realestate が本スクリプトの要。これが
# 抜けると既定値"erp"にフォールバックし、ERP版インスタンス(5011)と同じ
# aisb_erp.db を取り合って両デモのデータが混ざる/上書きされる。
cd "$(dirname "$0")"
export AISB_INSTANCE=realestate
export AISB_LEGACY_BASE_URL="${AISB_LEGACY_BASE_URL:-http://localhost:5030}"
export AISB_AI_PROVIDER="${AISB_AI_PROVIDER:-opencode}"
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 5031
