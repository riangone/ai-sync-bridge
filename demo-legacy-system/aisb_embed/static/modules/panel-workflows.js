// modules/panel-workflows.js — ワークフロー(マルチステップ自動化)パネル + AI解釈コメント
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.workflows = function renderWorkflowsPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-section-title">ワークフロー定義</div>
    <div id="aisb-wf-list">読込中...</div>
    <div class="aisb-section-title">実行履歴</div>
    <div id="aisb-wf-history">読込中...</div>
    <div class="aisb-btn-row">
      <button id="aisb-wf-insight-btn" class="aisb-btn-secondary">AIで傾向を解釈する</button>
    </div>
    <div id="aisb-wf-insight"></div>
  `;
  const listEl = el.querySelector("#aisb-wf-list");
  const historyEl = el.querySelector("#aisb-wf-history");
  const triggerLabel = { schedule: "定期実行", screen_navigation: "画面遷移時", data_update: "データ更新時", manual: "手動" };

  el.querySelector("#aisb-wf-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/workflows/history/insight`, e.target, el.querySelector("#aisb-wf-insight"))
  );

  function loadWorkflows() {
    fetch(`${ctx.API_BASE}/api/workflows`)
      .then((r) => r.json())
      .then((workflows) => {
        listEl.innerHTML =
          workflows
            .map(
              (wf) => `<div class="aisb-card" data-id="${wf.id}">
            <b>${wf.name}</b>${wf.enabled ? "" : ' <span class="aisb-badge">無効</span>'}<br>
            ${wf.description || ""}<br>
            トリガー: ${triggerLabel[wf.trigger.type] || wf.trigger.type} / ステップ数: ${wf.steps.length}
            <div class="aisb-btn-row">
              <button class="aisb-wf-exec-btn">実行</button>
              <button class="aisb-wf-toggle-btn aisb-btn-secondary">${wf.enabled ? "無効化" : "有効化"}</button>
            </div>
            <div class="aisb-wf-exec-result"></div>
          </div>`
            )
            .join("") || "<p>ワークフローがありません</p>";

        listEl.querySelectorAll(".aisb-wf-exec-btn").forEach((btn) => {
          btn.addEventListener("click", (ev) => {
            const card = ev.target.closest(".aisb-card");
            const id = card.dataset.id;
            const resultEl = card.querySelector(".aisb-wf-exec-result");
            resultEl.textContent = "実行中...";
            fetch(`${ctx.API_BASE}/api/workflows/${id}/execute`, {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ context: {} }),
            })
              .then((r) => r.json())
              .then((run) => {
                resultEl.innerHTML = `<span class="aisb-badge">結果: ${run.status}(${
                  run.steps.filter((s) => s.status === "success").length
                }/${run.steps.length}ステップ成功)</span>`;
                loadHistory();
              })
              .catch((e) => (resultEl.textContent = `エラー: ${e}`));
          });
        });

        listEl.querySelectorAll(".aisb-wf-toggle-btn").forEach((btn) => {
          btn.addEventListener("click", (ev) => {
            const id = ev.target.closest(".aisb-card").dataset.id;
            fetch(`${ctx.API_BASE}/api/workflows/${id}/toggle`, { method: "PATCH" })
              .then(() => loadWorkflows())
              .catch((e) => alert(`エラー: ${e}`));
          });
        });
      })
      .catch((e) => (listEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  function loadHistory() {
    fetch(`${ctx.API_BASE}/api/workflows/history/list`)
      .then((r) => r.json())
      .then((executions) => {
        historyEl.innerHTML =
          executions
            .map(
              (ex) => `<div class="aisb-event-card">
            <b>${ex.workflow_name}</b>: ${ex.status}(${ex.steps.filter((s) => s.status === "success").length}/${
                ex.steps.length
              }ステップ成功)
            <span class="aisb-event-time">${new Date(ex.finished_at).toLocaleString()}</span>
          </div>`
            )
            .join("") || "<p>実行履歴はまだありません</p>";
      })
      .catch((e) => (historyEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  loadWorkflows();
  loadHistory();
};
