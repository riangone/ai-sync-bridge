// modules/panel-analytics.js — 予測分析パネル(統計のみ) + AI解釈コメント(オプトイン)
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.analytics = function renderAnalyticsPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-section-title">売上予測(線形回帰)</div>
    <div id="aisb-forecast-chart">読込中...</div>
    <div class="aisb-btn-row">
      <button id="aisb-forecast-insight-btn" class="aisb-btn-secondary">AIでトレンドを解釈する</button>
    </div>
    <div id="aisb-forecast-insight"></div>
    <div class="aisb-section-title">再受注リスク予測</div>
    <div id="aisb-reorder-list">読込中...</div>
    <div class="aisb-btn-row">
      <button id="aisb-reorder-insight-btn" class="aisb-btn-secondary">AIでリスクを解釈する</button>
    </div>
    <div id="aisb-reorder-insight"></div>
  `;
  const chartEl = el.querySelector("#aisb-forecast-chart");
  const reorderEl = el.querySelector("#aisb-reorder-list");
  el.querySelector("#aisb-forecast-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/analytics/forecast/insight?months_ahead=3`, e.target, el.querySelector("#aisb-forecast-insight"))
  );
  el.querySelector("#aisb-reorder-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/analytics/reorder-predictions/insight`, e.target, el.querySelector("#aisb-reorder-insight"))
  );
  const riskLabel = { overdue: "要フォロー", due_soon: "近日予定", on_track: "順調" };

  fetch(`${ctx.API_BASE}/api/analytics/forecast?months_ahead=3`)
    .then((r) => r.json())
    .then((data) => {
      const points = data.points || [];
      if (!points.length) {
        chartEl.innerHTML = "<p>受注データがありません</p>";
        return;
      }
      const max = Math.max(...points.map((p) => p.actual ?? p.predicted ?? 0), 1);
      chartEl.innerHTML =
        `<div class="aisb-legend">
           <span><span class="aisb-legend-dot" style="background:#2a78d6"></span>実績</span>
           <span><span class="aisb-legend-dot" style="background:#9ec5f4"></span>予測(${data.method})</span>
         </div>
         <div class="aisb-chart">` +
        points
          .map((p) => {
            const isForecast = p.actual === null || p.actual === undefined;
            const value = isForecast ? p.predicted : p.actual;
            const h = Math.max(4, Math.round((value / max) * 100));
            return `<div class="aisb-bar-col" title="${p.month}: ${Math.round(value).toLocaleString()}円">
              <div class="aisb-bar${isForecast ? " aisb-bar-forecast" : ""}" style="height:${h}%"></div>
              <div class="aisb-bar-label">${p.month.slice(2)}</div>
            </div>`;
          })
          .join("") +
        `</div>`;
    })
    .catch((e) => (chartEl.innerHTML = `<p>エラー: ${e}</p>`));

  fetch(`${ctx.API_BASE}/api/analytics/reorder-predictions`)
    .then((r) => r.json())
    .then((data) => {
      const preds = data.predictions || [];
      reorderEl.innerHTML =
        preds
          .map(
            (p) => `<div class="aisb-card aisb-risk-${p.risk}">
          <b>${p.customer_name}</b><span class="aisb-risk-tag">${riskLabel[p.risk] || p.risk}</span><br>
          前回受注: ${p.last_order_date} / 平均間隔: ${p.avg_interval_days}日<br>
          次回予測: ${p.expected_next_date} (${p.days_until_expected >= 0 ? `あと${p.days_until_expected}日` : `${-p.days_until_expected}日超過`})
        </div>`
          )
          .join("") || "<p>予測対象の受注履歴がありません</p>";
    })
    .catch((e) => (reorderEl.innerHTML = `<p>エラー: ${e}</p>`));
};
