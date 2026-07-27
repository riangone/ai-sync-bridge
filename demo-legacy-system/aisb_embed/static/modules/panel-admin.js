// modules/panel-admin.js — 管理パネル(システム統計/監査ログ/デモデータリセット)
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.admin = function renderAdminPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-section-title">システム状況</div>
    <div id="aisb-admin-stats">読込中...</div>
    <div class="aisb-btn-row">
      <button id="aisb-admin-reset" class="aisb-btn-secondary">デモデータをリセット</button>
      <button id="aisb-admin-insight-btn" class="aisb-btn-secondary">AIで統計を解釈する</button>
    </div>
    <div id="aisb-admin-insight"></div>
    <div class="aisb-section-title">監査ログ</div>
    <div id="aisb-admin-audit">読込中...</div>
  `;
  const statsEl = el.querySelector("#aisb-admin-stats");
  const auditEl = el.querySelector("#aisb-admin-audit");
  el.querySelector("#aisb-admin-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/admin/stats/insight`, e.target, el.querySelector("#aisb-admin-insight"))
  );

  function loadStats() {
    fetch(`${ctx.API_BASE}/api/admin/stats`)
      .then((r) => r.json())
      .then((s) => {
        statsEl.innerHTML = `
          <div class="aisb-card">
            モード: ${s.demo_mode ? "デモ" : "本番"} / AI: ${s.ai_provider} / 検索: ${s.vector_backend}<br>
            顧客数: ${s.customer_count} / 受注数: ${s.order_count}<br>
            ワークフロー: ルール${s.workflow_rule_count}件 / 発火${s.workflow_event_count}件<br>
            未読通知: ${s.unread_notification_count}件
          </div>`;
      })
      .catch((e) => (statsEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  function loadAudit() {
    fetch(`${ctx.API_BASE}/api/admin/audit-log`)
      .then((r) => r.json())
      .then((entries) => {
        auditEl.innerHTML =
          entries
            .map(
              (a) => `<div class="aisb-event-card">
            [${a.action}] ${a.detail}
            <span class="aisb-event-time">${new Date(a.at).toLocaleString()} (${a.actor})</span>
          </div>`
            )
            .join("") || "<p>監査ログはまだありません</p>";
      })
      .catch((e) => (auditEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  el.querySelector("#aisb-admin-reset").addEventListener("click", () => {
    if (!confirm("デモデータ(顧客/受注/会話履歴)を初期状態にリセットします。よろしいですか?")) return;
    fetch(`${ctx.API_BASE}/api/admin/reset-demo-data`, { method: "POST" })
      .then((r) => r.json())
      .then(() => {
        loadStats();
        loadAudit();
        ctx.refreshUnreadBadge();
      })
      .catch((e) => alert(`エラー: ${e}`));
  });

  loadStats();
  loadAudit();
};
