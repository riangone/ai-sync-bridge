// AI-Sync 全サービスの pm2 定義。サーバー再起動後も `pm2 resurrect`(systemd pm2-ubuntu)で自動復帰させる。
// 起動: pm2 start ecosystem.config.js && pm2 save
const path = require("path");
const ROOT = __dirname;

const demos = [
  { name: "erp",        dir: "demo-legacy-system",            port: 5010 },
  { name: "dealer",     dir: "demo-legacy-system-dealer",     port: 5020 },
  { name: "realestate", dir: "demo-legacy-system-realestate", port: 5030 },
  { name: "koseki",     dir: "demo-legacy-system-koseki",     port: 5040 },
  { name: "nenkin",     dir: "demo-legacy-system-nenkin",     port: 5050 },
];

const apps = [
  // opencode serve(127.0.0.1:4096) は pm2 では管理しない。2026-10-26 のリモートコマンド実行インシデントを受け、
  // 専用ユーザー + systemd サンドボックス(ops/opencode/aisync-opencode.service)で動かす。
  // 導入/設定反映: sudo ops/opencode/install.sh
];

for (const d of demos) {
  // レガシーデモ本体。main.py の __main__ は reload=True なので使わず uvicorn を直接起動する。
  apps.push({
    name: `aisync-demo-${d.name}`,
    cwd: path.join(ROOT, d.dir),
    script: ".venv/bin/python",
    args: `-m uvicorn main:app --host 0.0.0.0 --port ${d.port}`,
    interpreter: "none",
  });
  // AI API インスタンス。AISB_INSTANCE 等は start-*.sh 側で設定される(DB 混線防止)。
  apps.push({
    name: `aisync-api-${d.name}`,
    cwd: path.join(ROOT, "ai-api-server"),
    script: `start-${d.name}.sh`,
    interpreter: "bash",
  });
}

module.exports = {
  apps: apps.map((a) => ({ autorestart: true, max_restarts: 20, restart_delay: 3000, ...a })),
};
