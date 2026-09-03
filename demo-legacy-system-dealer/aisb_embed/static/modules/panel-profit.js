// modules/panel-profit.js — 利益・粗利パネル(README 4.3 panel-profit.js相当)
// POST /api/profit-report/report?period=YYYY-MM(任意) → 商品別売上/原価/粗利
// AIによる解釈が欲しい場合は GET /api/profit-report/report/insight をオプトインで呼ぶ
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.profit = function renderProfitPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-inline-row">
      <input type="text" id="aisb-profit-period" placeholder="対象期間 YYYY-MM(空欄で全期間)" />
      <button id="aisb-profit-run">レポート生成</button>
    </div>
    <div id="aisb-profit-result"></div>
    <div class="aisb-btn-row">
      <button id="aisb-profit-insight-btn" class="aisb-btn-secondary">AIで収益性を解釈する</button>
    </div>
    <div id="aisb-profit-insight"></div>
  `;
  const resultEl = el.querySelector("#aisb-profit-result");

  el.querySelector("#aisb-profit-insight-btn").addEventListener("click", (e) => {
    const period = el.querySelector("#aisb-profit-period").value.trim();
    const url = `${ctx.API_BASE}/api/profit-report/report/insight${period ? `?period=${encodeURIComponent(period)}` : ""}`;
    ctx.runInsight(url, e.target, el.querySelector("#aisb-profit-insight"));
  });

  el.querySelector("#aisb-profit-run").addEventListener("click", (e) => {
    const btn = e.target;
    const period = el.querySelector("#aisb-profit-period").value.trim();
    btn.disabled = true;
    resultEl.textContent = "集計中...";
    const url = `${ctx.API_BASE}/api/profit-report/report${period ? `?period=${encodeURIComponent(period)}` : ""}`;
    fetch(url, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        const details = data.product_details || [];
        resultEl.innerHTML = `
          <div class="aisb-card aisb-summary-card">${ctx.escapeHtml(data.summary)}</div>
          <div class="aisb-badge">粗利合計: ${Math.round(data.total_profit).toLocaleString()}円${data.period ? ` / 対象: ${ctx.escapeHtml(data.period)}` : ""}</div>
          <table class="aisb-table">
            <thead><tr><th>商品名</th><th>数量</th><th>売上</th><th>原価</th><th>粗利</th><th>粗利率</th></tr></thead>
            <tbody>${details
              .map(
                (d) => `<tr>
                  <td>${ctx.escapeHtml(d.product_name)}${d.cost_known ? "" : ' <span class="aisb-badge">原価未登録</span>'}</td>
                  <td>${d.qty}</td>
                  <td>${Math.round(d.revenue).toLocaleString()}円</td>
                  <td>${Math.round(d.cost).toLocaleString()}円</td>
                  <td>${Math.round(d.profit).toLocaleString()}円</td>
                  <td>${Math.round(d.margin_rate * 100)}%</td>
                </tr>`
              )
              .join("")}</tbody>
          </table>` || "<p>対象データがありません</p>";
      })
      .catch((e) => (resultEl.innerHTML = `<p>エラー: ${e}</p>`))
      .finally(() => (btn.disabled = false));
  });
};
