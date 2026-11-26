#!/bin/bash
# A2A 連携(ERP <-> CRM, ERP <-> 物流)の共有キーを生成する。既存のキーは上書きせず、足りないキーだけ追記する
# (キーを変えると稼働中の相手側と食い違うため)。作り直すときはファイルを消してから実行し、全インスタンスを再起動する。
#
#   AISB_A2A_ERP_PEER_KEY  ERP Agent -> CRM Bridge の /a2a で使う(CRM 側では a2a_erp_agent 主体)
#   AISB_A2A_CRM_PEER_KEY  CRM Agent -> ERP Bridge の /a2a で使う(ERP 側では a2a_crm_agent 主体)
#   AISB_A2A_ERP_LOGI_KEY  ERP Agent -> 物流 Bridge の /a2a で使う(物流側では a2a_erp_agent 主体)
#   AISB_A2A_LOGI_ERP_KEY  物流 Agent -> ERP Bridge の /a2a で使う(ERP 側では a2a_logistics_agent 主体)
#   AISB_CRM_SUPPORT_KEY   CRM Bridge の運用確認用(サポート主体)。公開画面からは使わない
#   AISB_CRM_ADMIN_KEY     CRM Bridge の管理操作用
#   AISB_LOGI_ADMIN_KEY    物流 Bridge の管理操作用
#
# 読み込み: ops/load-a2a-secrets.sh(各起動スクリプトが「自分に必要なキーだけ」を指定して読む)
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="${1:-$ROOT/ops/secrets/a2a.env}"
KEYS=(AISB_A2A_ERP_PEER_KEY AISB_A2A_CRM_PEER_KEY AISB_A2A_ERP_LOGI_KEY AISB_A2A_LOGI_ERP_KEY
      AISB_CRM_SUPPORT_KEY AISB_CRM_ADMIN_KEY AISB_LOGI_ADMIN_KEY)
umask 077
mkdir -p "$(dirname "$OUT")"
[ -e "$OUT" ] || echo "# generated $(date -Iseconds) by ops/gen-a2a-secrets.sh — do not commit" >"$OUT"
gen() { python3 -c 'import secrets; print(secrets.token_urlsafe(32))'; }
added=0
for k in "${KEYS[@]}"; do
  if ! grep -q "^${k}=" "$OUT"; then
    echo "${k}=$(gen)" >>"$OUT"
    added=$((added + 1))
  fi
done
chmod 600 "$OUT"
echo "ok: $OUT (added $added key(s))"
