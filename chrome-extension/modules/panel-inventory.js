// modules/panel-inventory.js — 在庫管理パネル(README 4.3 panel-inventory.js相当)
// GET /api/inventory(商品一覧) + GET /api/inventory/anomalies(reorder_point割れ異常検知)
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.inventory = function renderInventoryPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-section-title">在庫一覧</div>
    <div id="aisb-inv-list">読込中...</div>
    <div class="aisb-section-title">異常検知(発注点割れ)</div>
    <div class="aisb-btn-row">
      <button id="aisb-inv-anomaly-btn">異常検知を実行</button>
    </div>
    <div id="aisb-inv-anomalies"></div>
  `;
  const listEl = el.querySelector("#aisb-inv-list");
  const anomalyEl = el.querySelector("#aisb-inv-anomalies");

  function loadList() {
    fetch(`${ctx.API_BASE}/api/inventory`)
      .then((r) => r.json())
      .then((products) => {
        if (!products.length) {
          listEl.innerHTML = "<p>商品データがありません</p>";
          return;
        }
        listEl.innerHTML = `<table class="aisb-table">
          <thead><tr><th>商品名</th><th>SKU</th><th>在庫</th><th>発注点</th><th>原価</th><th>仕入先</th></tr></thead>
          <tbody>${products
            .map(
              (p) => `<tr${p.stock <= p.reorder_point ? ' class="aisb-notif-unread"' : ""}>
                <td>${ctx.escapeHtml(p.name)}</td><td>${ctx.escapeHtml(p.sku)}</td>
                <td>${p.stock}</td><td>${p.reorder_point}</td>
                <td>${Math.round(p.unit_cost).toLocaleString()}円</td><td>${ctx.escapeHtml(p.supplier)}</td>
              </tr>`
            )
            .join("")}</tbody>
        </table>`;
      })
      .catch((e) => (listEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  el.querySelector("#aisb-inv-anomaly-btn").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    anomalyEl.textContent = "検知中...";
    fetch(`${ctx.API_BASE}/api/inventory/anomalies`)
      .then((r) => r.json())
      .then((data) => {
        const items = data.anomalies || [];
        anomalyEl.innerHTML =
          items
            .map(
              (a) => `<div class="aisb-card aisb-risk-${a.severity === "critical" ? "overdue" : "due_soon"}">
            <b>${ctx.escapeHtml(a.product_name)}</b><span class="aisb-risk-tag">${a.severity === "critical" ? "在庫切れ" : "発注点割れ"}</span><br>
            在庫 ${a.stock} / 発注点 ${a.reorder_point}(不足 ${a.shortage})
          </div>`
            )
            .join("") || "<p>異常はありません</p>";
      })
      .catch((e) => (anomalyEl.innerHTML = `<p>エラー: ${e}</p>`))
      .finally(() => (btn.disabled = false));
  });

  loadList();
};
