#!/bin/bash
# ai-api-server を「年金相談業務版(demo-legacy-system-nenkin, port 5050)向け
# インスタンス」として起動する。AISB_INSTANCE=nenkin が本スクリプトの要。これが
# 抜けると既定値"erp"にフォールバックし、ERP版インスタンス(5011)と同じ
# aisb_erp.db を取り合って両デモのデータが混ざる/上書きされる。
cd "$(dirname "$0")"
export AISB_INSTANCE=nenkin
export AISB_LEGACY_BASE_URL="${AISB_LEGACY_BASE_URL:-http://localhost:5050}"
source ./ai-provider.sh
exec .venv/bin/python -m uvicorn app.main:app --host 0.0.0.0 --port 5051
