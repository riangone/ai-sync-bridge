#!/bin/bash
# ai-api-server を「CRM版(demo-legacy-system-crm, port 5020)向けインスタンス」として起動する。
cd "$(dirname "$0")"
export AISB_INSTANCE=crm
export AISB_DOMAINS=""
export AISB_LEGACY_BASE_URL="${AISB_LEGACY_BASE_URL:-http://localhost:5020}"
export AISB_BRIDGE_PROFILE="${AISB_BRIDGE_PROFILE:-../demo-legacy-system-crm/aisb_profile/bridge.yaml}"
source ./ai-provider.sh
source ../ops/load-a2a-secrets.sh AISB_A2A_ERP_PEER_KEY AISB_A2A_CRM_PEER_KEY AISB_CRM_SUPPORT_KEY AISB_CRM_ADMIN_KEY
exec .venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 5021
