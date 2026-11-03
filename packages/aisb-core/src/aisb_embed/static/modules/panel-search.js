// modules/panel-search.js — セマンティック検索パネル
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.search = function renderSearchPanel(el, ctx) {
  el.innerHTML = `
    <div id="aisb-search-row">
      <input id="aisb-search-input" type="text" placeholder="自然文/キーワードで検索..." />
      <button id="aisb-search-run">検索</button>
    </div>
    <div id="aisb-search-results"></div>
  `;
  async function run() {
    const q = el.querySelector("#aisb-search-input").value.trim();
    const resultsEl = el.querySelector("#aisb-search-results");
    if (!q) return;
    resultsEl.textContent = "検索中...";
    try {
      const res = await fetch(`${ctx.API_BASE}/api/search`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ query: q, top_k: 5 }),
      });
      const data = await res.json();
      resultsEl.innerHTML =
        `<div class="aisb-badge">backend: ${data.backend}</div>` +
        data.results.map((r) => `<div class="aisb-card"><b>${r.title}</b> (score ${r.score})<br>${r.snippet}</div>`).join("");
    } catch (e) {
      resultsEl.textContent = `エラー: ${e}`;
    }
  }
  el.querySelector("#aisb-search-run").addEventListener("click", run);
  el.querySelector("#aisb-search-input").addEventListener("keydown", (e) => e.key === "Enter" && run());
};
