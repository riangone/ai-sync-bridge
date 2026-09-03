// modules/panel-arap.js — 売掛・買掛(AR/AP)パネル(README 4.3 panel-arap.js相当)
// POST /api/ar-ap/aging → 取引先別エイジング分析 + ルールベースの集計コメント(summary)
// AIによる解釈が欲しい場合は GET /api/ar-ap/aging/insight をオプトインで呼ぶ
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.arap = function renderArApPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-btn-row">
      <button id="aisb-arap-run">エイジング分析を実行</button>
    </div>
    <div id="aisb-arap-result"></div>
    <div class="aisb-btn-row">
      <button id="aisb-arap-insight-btn" class="aisb-btn-secondary">AIでリスクを解釈する</button>
    </div>
    <div id="aisb-arap-insight"></div>
  `;
  const resultEl = el.querySelector("#aisb-arap-result");

  el.querySelector("#aisb-arap-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/ar-ap/aging/insight`, e.target, el.querySelector("#aisb-arap-insight"))
  );
  const riskClass = { low: "on_track", medium: "due_soon", high: "overdue" };
  const riskLabel = { low: "低", medium: "中", high: "高" };
  const typeLabel = { receivable: "売掛", payable: "買掛" };

  el.querySelector("#aisb-arap-run").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    resultEl.textContent = "集計中...";
    fetch(`${ctx.API_BASE}/api/ar-ap/aging`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        const rows = data.aging_report || [];
        resultEl.innerHTML = `
          <div class="aisb-card aisb-summary-card">${ctx.escapeHtml(data.summary)}</div>
          <div class="aisb-badge">売掛合計: ${Math.round(data.total_receivable).toLocaleString()}円</div>
          <div class="aisb-badge">買掛合計: ${Math.round(data.total_payable).toLocaleString()}円</div>
          ${
            rows
              .map(
                (r) => `<div class="aisb-card aisb-risk-${riskClass[r.risk] || "on_track"}">
              <b>${ctx.escapeHtml(r.entity_name)}</b>
              <span class="aisb-badge">${typeLabel[r.entity_type] || r.entity_type}</span>
              <span class="aisb-risk-tag">リスク:${riskLabel[r.risk] || r.risk}</span><br>
              期日前:${Math.round(r.current).toLocaleString()} / 1-30日:${Math.round(r.bucket_1_30).toLocaleString()} /
              31-60日:${Math.round(r.bucket_31_60).toLocaleString()} / 61-90日:${Math.round(r.bucket_61_90).toLocaleString()} /
              91日以上:${Math.round(r.bucket_90_plus).toLocaleString()}<br>
              合計: ${Math.round(r.total).toLocaleString()}円
            </div>`
              )
              .join("") || "<p>対象データがありません</p>"
          }`;
      })
      .catch((e) => (resultEl.innerHTML = `<p>エラー: ${e}</p>`))
      .finally(() => (btn.disabled = false));
  });
};
