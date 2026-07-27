// modules/panel-workflows.js — ワークフロー(自動化ルール)パネル + AI解釈コメント
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.workflows = function renderWorkflowsPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-section-title">自動化ルール</div>
    <div id="aisb-wf-rules">読込中...</div>
    <div class="aisb-btn-row">
      <button id="aisb-wf-run">ルールを評価する</button>
    </div>
    <div class="aisb-section-title">発火履歴</div>
    <div id="aisb-wf-history">読込中...</div>
    <div class="aisb-btn-row">
      <button id="aisb-wf-insight-btn" class="aisb-btn-secondary">AIで傾向を解釈する</button>
    </div>
    <div id="aisb-wf-insight"></div>
  `;
  const rulesEl = el.querySelector("#aisb-wf-rules");
  const historyEl = el.querySelector("#aisb-wf-history");
  el.querySelector("#aisb-wf-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/workflows/history/insight`, e.target, el.querySelector("#aisb-wf-insight"))
  );

  function loadRules() {
    fetch(`${ctx.API_BASE}/api/workflows/rules`)
      .then((r) => r.json())
      .then((rules) => {
        rulesEl.innerHTML =
          rules
            .map(
              (r) => `<div class="aisb-card">
            <b>${r.name}</b><br>
            条件: ${r.entity}.${r.field} ${r.operator} ${r.value} → ${r.action}
          </div>`
            )
            .join("") || "<p>ルールがありません</p>";
      })
      .catch((e) => (rulesEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  function loadHistory() {
    fetch(`${ctx.API_BASE}/api/workflows/history`)
      .then((r) => r.json())
      .then((events) => {
        historyEl.innerHTML =
          events
            .map(
              (ev) => `<div class="aisb-event-card">
            <b>${ev.rule_name}</b>: ${ev.message}
            <span class="aisb-event-time">${new Date(ev.triggered_at).toLocaleString()}</span>
          </div>`
            )
            .join("") || "<p>発火履歴はまだありません</p>";
      })
      .catch((e) => (historyEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  el.querySelector("#aisb-wf-run").addEventListener("click", async () => {
    historyEl.textContent = "評価中...";
    try {
      const res = await fetch(`${ctx.API_BASE}/api/workflows/run`, { method: "POST" });
      const data = await res.json();
      loadHistory();
      if (data.new_events.length === 0) {
        historyEl.insertAdjacentHTML("afterbegin", `<div class="aisb-badge">新規発火なし(全て評価済み)</div>`);
      }
    } catch (e) {
      historyEl.textContent = `エラー: ${e}`;
    }
  });

  loadRules();
  loadHistory();
};
