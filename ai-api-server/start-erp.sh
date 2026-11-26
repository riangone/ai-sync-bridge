#!/bin/bash
# ai-api-server を「ERP版(demo-legacy-system, port 5010)向けインスタンス」として起動する。
# AISB_INSTANCE=erp が無いと既定値"erp"にフォールバックするため実害は無いが、
# start-dealer.sh と対で明示しておくことで「envを設定し忘れて2インスタンスが
# 同じSQLiteファイルを取り合う」事故を構造的に防ぐ。
cd "$(dirname "$0")"
export AISB_INSTANCE=erp
export AISB_LEGACY_BASE_URL="${AISB_LEGACY_BASE_URL:-http://localhost:5010}"
export AISB_BRIDGE_PROFILE="${AISB_BRIDGE_PROFILE:-../demo-legacy-system/aisb_profile/bridge.yaml}"
source ./ai-provider.sh
source ../ops/load-a2a-secrets.sh AISB_A2A_ERP_PEER_KEY AISB_A2A_CRM_PEER_KEY AISB_A2A_ERP_LOGI_KEY AISB_A2A_LOGI_ERP_KEY
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 5011
