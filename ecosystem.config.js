// AI-Sync 全サービスの pm2 定義。サーバー再起動後も `pm2 resurrect`(systemd pm2-ubuntu)で自動復帰させる。
// 起動: pm2 start ecosystem.config.js && pm2 save
const path = require("path");
const ROOT = __dirname;

// 公開するデモは ERP と、ERP と A2A で連携する CRM(2026-11)。dealer / realestate / koseki / nenkin は
// 一時的に公開を止めたのではなく、スコープを絞るために撤去した。コードは
// demo-legacy-system-* に残っているが、pm2 定義・Caddy・landing からは外している。
// CRM は 5020/5021 を使う(旧 dealer の番号。dealer の Caddy 経路は撤去済み)。
// script を持つデモは A2A キー(ops/secrets/a2a.env)を読み込むため起動スクリプト経由で動かす。
const demos = [
  { name: "erp", dir: "demo-legacy-system", port: 5010 },
  { name: "crm", dir: "demo-legacy-system-crm", port: 5020, script: "start.sh" },
];

const apps = [
  // opencode serve(127.0.0.1:4096) は pm2 では管理しない。2026-10-26 のリモートコマンド実行インシデントを受け、
  // 専用ユーザー + systemd サンドボックス(ops/opencode/aisync-opencode.service)で動かす。
  // 導入/設定反映: sudo ops/opencode/install.sh
];

for (const d of demos) {
  // レガシーデモ本体。main.py の __main__ は reload=True なので使わず uvicorn を直接起動する。
  apps.push(d.script
    ? { name: `aisync-demo-${d.name}`, cwd: path.join(ROOT, d.dir), script: d.script, interpreter: "bash" }
    : {
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
