#!/bin/bash
# ai-api-server を「物流版(demo-legacy-system-logistics, port 5030)向けインスタンス」として起動する。
cd "$(dirname "$0")"
export AISB_INSTANCE=logistics
export AISB_DOMAINS=""
export AISB_LEGACY_BASE_URL="${AISB_LEGACY_BASE_URL:-http://localhost:5030}"
export AISB_BRIDGE_PROFILE="${AISB_BRIDGE_PROFILE:-../demo-legacy-system-logistics/aisb_profile/bridge.yaml}"
source ./ai-provider.sh
source ../ops/load-a2a-secrets.sh AISB_A2A_ERP_LOGI_KEY AISB_A2A_LOGI_ERP_KEY AISB_LOGI_ADMIN_KEY
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 5031
