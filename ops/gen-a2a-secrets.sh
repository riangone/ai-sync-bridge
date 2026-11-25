#!/bin/bash
# A2A 連携(ERP <-> CRM)の共有キーを生成する。既存のファイルは上書きしない(キーを変えると
# 稼働中の相手側と食い違うため)。作り直すときはファイルを消してから実行し、両インスタンスを再起動する。
#
#   AISB_A2A_ERP_PEER_KEY  ERP Agent -> CRM Bridge の /a2a で使う(CRM 側では a2a_erp_agent 主体)
#   AISB_A2A_CRM_PEER_KEY  CRM Agent -> ERP Bridge の /a2a で使う(ERP 側では a2a_crm_agent 主体)
#   AISB_CRM_SUPPORT_KEY   CRM Bridge の運用確認用(サポート主体)。公開画面からは使わない
#   AISB_CRM_ADMIN_KEY     CRM Bridge の管理操作用
#
# 読み込み: ai-api-server/start-{erp,crm}.sh と demo-legacy-system-crm/start.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/ops/secrets/a2a.env}"
if [ -e "$OUT" ]; then
  echo "exists, not overwritten: $OUT" >&2
  exit 0
fi
umask 077
mkdir -p "$(dirname "$OUT")"
gen() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
{
  echo "# generated $(date -Iseconds) by ops/gen-a2a-secrets.sh — do not commit"
  echo "AISB_A2A_ERP_PEER_KEY=$(gen)"
  echo "AISB_A2A_CRM_PEER_KEY=$(gen)"
  echo "AISB_CRM_SUPPORT_KEY=$(gen)"
  echo "AISB_CRM_ADMIN_KEY=$(gen)"
} >"$OUT"
chmod 600 "$OUT"
echo "written: $OUT"
