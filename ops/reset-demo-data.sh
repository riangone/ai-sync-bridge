#!/bin/bash
# 公開デモのデータを毎日初期状態へ戻す(訪問者がフォームから入力した内容を残さないため)。
#
# 1. 各デモを止めて SQLite を削除し、再起動する(data.py が固定シードから作り直す)
# 2. AI API 側のデモデータを初期化する(本機直結のみ許可される管理操作)
# 3. ブリッジを同期し、消えた行を検索インデックスと全文データからも取り除く
#
# ログには件数と状態だけを書き、レコードの内容は出さない。
# 実行例(crontab): 10 4 * * * /usr/bin/flock -n /tmp/aisync-demo-reset.lock <repo>/ops/reset-demo-data.sh >> ~/.cache/aisync/demo-reset.log 2>&1
set -u

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
export PATH="/usr/local/bin:/usr/bin:/bin:${PATH:-}"

# pm2名 ディレクトリ DBファイル デモのポート APIのポート
# 公開しているデモはERPのみ。他業種のデモは pm2 / Caddy から外しており、ここにも載せない。
DEMOS=(
  "erp demo-legacy-system erp.db 5010 5011"
)
BRIDGE_API_PORT=5011
BRIDGE_DB="$ROOT/ai-api-server/data/bridge_erp.db"

failures=0
log() { echo "$(date '+%F %T %z') $*"; }
fail() { log "ERROR $*"; failures=$((failures + 1)); }

wait_http_200() {  # url タイムアウト秒
  local deadline=$((SECONDS + $2))
  while [ "$SECONDS" -lt "$deadline" ]; do
    [ "$(curl -s -o /dev/null -m 3 -w '%{http_code}' "$1")" = "200" ] && return 0
    sleep 1
  done
  return 1
}

log "start"

for entry in "${DEMOS[@]}"; do
  read -r name dir db demo_port api_port <<<"$entry"
  proc="aisync-demo-$name"
  if ! pm2 stop "$proc" >/dev/null 2>&1; then
    # 止まっていないプロセスの下で DB を消すと壊れるので、削除しない
    fail "$name: stop failed, db kept"
    continue
  fi
  rm -f -- "$ROOT/$dir/$db" "$ROOT/$dir/$db-wal" "$ROOT/$dir/$db-shm" || fail "$name: db delete failed"
  pm2 start "$proc" >/dev/null 2>&1 || fail "$name: start failed"
  if wait_http_200 "http://127.0.0.1:$demo_port/" 60; then
    log "$name: demo reseeded"
  else
    fail "$name: demo did not return 200"
  fi

  code="$(curl -s -o /dev/null -m 30 -w '%{http_code}' -X POST "http://127.0.0.1:$api_port/api/admin/reset-demo-data")"
  if [ "$code" = "200" ]; then
    log "$name: api data reset"
  else
    fail "$name: api reset returned $code"
  fi
done

# 公開の同期ボタンと共有のクールダウンに当たったら(cached)、明けるまで待ってやり直す
sync_bridge() {
  curl -s -m 300 -X POST "http://127.0.0.1:$BRIDGE_API_PORT/api/bridge/demo/sync"
}
result="$(sync_bridge)"
if printf '%s' "$result" | grep -q '"cached":true'; then
  sleep 65
  result="$(sync_bridge)"
fi
if printf '%s' "$result" | python3 -c '
import json, sys
d = json.load(sys.stdin)
if d.get("cached"):
    sys.exit("still cached")
failed = [e.get("entity") for e in d.get("entities", []) if e.get("failed")]
if failed or not d.get("entities"):
    sys.exit("failed entities=%s" % failed)
print("bridge: synced", {k: d[k] for k in ("upserted", "deleted", "unchanged") if k in d})
'; then
  # 削除した文書の断片が DB の空きページに残らないよう、ファイルを詰め直す
  if python3 - "$BRIDGE_DB" <<'PY'
import sqlite3, sys
conn = sqlite3.connect(sys.argv[1], timeout=30)
conn.execute("VACUUM")
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
conn.close()
PY
  then
    log "bridge: vacuumed"
  else
    fail "bridge: vacuum failed"
  fi
else
  fail "bridge: sync failed"
fi

log "done failures=$failures"
[ "$failures" -eq 0 ]
