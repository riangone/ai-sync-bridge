// modules/panel-customers.js — 顧客検索パネル(ai-api-server側デモ顧客データ)
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.customers = function renderCustomersPanel(el, ctx) {
  el.innerHTML = `<div id="aisb-customers-list">読込中...</div>`;
  const list = el.querySelector("#aisb-customers-list");
  fetch(`${ctx.API_BASE}/api/customers`)
    .then((r) => r.json())
    .then((rows) => {
      list.innerHTML = rows
        .map((c) => `<div class="aisb-card"><b>${c.name}</b><br>${c.company || ""}<br>${c.email || ""}</div>`)
        .join("") || "<p>顧客データがありません</p>";
    })
    .catch((e) => (list.innerHTML = `<p>エラー: ${e}</p>`));
};
