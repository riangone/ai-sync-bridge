#!/usr/bin/env bash
# AI-Sync 用 opencode をサンドボックス化した systemd サービスとして導入/更新する。
# 使い方: sudo ops/opencode/install.sh   (設定変更後も同じコマンドで再適用)
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
BASE=/srv/aisync-ai

id aisync-ai >/dev/null 2>&1 || useradd --system --home-dir "$BASE" --no-create-home --shell /usr/sbin/nologin aisync-ai
install -d -o aisync-ai -g aisync-ai -m 750 "$BASE"
for d in sandbox xdg-config data cache state; do install -d -o aisync-ai -g aisync-ai -m 750 "$BASE/$d"; done
# サンドボックスは常に空に保つ(プロジェクト設定/AGENTS.md 等を置かせない)
find "$BASE/sandbox" -mindepth 1 -delete
find "$BASE/xdg-config" -mindepth 1 -delete
install -o root -g aisync-ai -m 640 "$HERE/aisync-opencode.json" "$BASE/opencode.json"
install -o root -g root -m 644 "$HERE/aisync-opencode.service" /etc/systemd/system/aisync-opencode.service
systemctl daemon-reload
systemctl enable aisync-opencode.service
systemctl restart aisync-opencode.service
echo "installed. status: $(systemctl is-active aisync-opencode.service)"
