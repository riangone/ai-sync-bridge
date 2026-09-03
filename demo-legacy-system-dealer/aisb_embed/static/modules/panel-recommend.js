// modules/panel-recommend.js — 類似レコード推薦パネル(README 4.3 panel-recommend.js相当)
// POST /api/recommend(tableName, id, maxResults, includeExplanation) → 類似レコード一覧
// (一致理由の説明文はルールベース。本物のAI解釈は GET /api/recommend/insight でオプトイン)
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.recommend = function renderRecommendPanel(el, ctx) {
  el.innerHTML = `
    <p class="aisb-hint">レガシー画面のテーブル/IDを指定すると、文字類似度(bi-gram)ベースで近しいレコードを検索します。</p>
    <div class="aisb-inline-row">
      <select id="aisb-rec-table">
        <option value="customers">顧客(customers)</option>
        <option value="orders">受注(orders)</option>
        <option value="products">商品(products)</option>
      </select>
      <input type="number" id="aisb-rec-id" placeholder="ID" style="width:70px" />
    </div>
    <div class="aisb-inline-row">
      <input type="number" id="aisb-rec-max" placeholder="件数" value="5" style="width:70px" />
      <label style="font-size:12px;display:flex;align-items:center;gap:4px">
        <input type="checkbox" id="aisb-rec-ai" checked />説明を付与
      </label>
      <button id="aisb-rec-run">類似レコードを検索</button>
    </div>
    <div id="aisb-rec-result"></div>
    <div class="aisb-btn-row">
      <button id="aisb-rec-insight-btn" class="aisb-btn-secondary">AIで関連性を解釈する</button>
    </div>
    <div id="aisb-rec-insight"></div>
  `;
  const resultEl = el.querySelector("#aisb-rec-result");

  function currentQuery() {
    const tableName = el.querySelector("#aisb-rec-table").value;
    const id = el.querySelector("#aisb-rec-id").value;
    const maxResults = Number(el.querySelector("#aisb-rec-max").value) || 5;
    return { tableName, id, maxResults };
  }

  el.querySelector("#aisb-rec-insight-btn").addEventListener("click", (e) => {
    const { tableName, id, maxResults } = currentQuery();
    if (!id) {
      alert("IDを入力してください");
      return;
    }
    ctx.runInsight(
      `${ctx.API_BASE}/api/recommend/insight?table_name=${encodeURIComponent(tableName)}&id=${Number(id)}&max_results=${maxResults}`,
      e.target,
      el.querySelector("#aisb-rec-insight")
    );
  });

  el.querySelector("#aisb-rec-run").addEventListener("click", () => {
    const { tableName, id, maxResults } = currentQuery();
    const includeExplanation = el.querySelector("#aisb-rec-ai").checked;
    if (!id) {
      alert("IDを入力してください");
      return;
    }
    resultEl.textContent = "検索中...";
    ctx
      .postJson(`${ctx.API_BASE}/api/recommend`, {
        table_name: tableName,
        id: Number(id),
        max_results: maxResults,
        include_explanation: includeExplanation,
      })
      .then((data) => {
        const results = data.results || [];
        resultEl.innerHTML =
          results
            .map(
              (r) => `<div class="aisb-card">
            <b>ID:${r.id}</b><span class="aisb-badge">類似度 ${Math.round(r.score * 100)}%</span><br>
            ${ctx.escapeHtml(r.text)}
            ${r.explanation ? `<div class="aisb-summary-card" style="margin-top:6px;padding:6px 8px;border-radius:4px">${ctx.escapeHtml(r.explanation)}</div>` : ""}
          </div>`
            )
            .join("") || "<p>類似レコードが見つかりませんでした</p>";
      })
      .catch((e) => (resultEl.innerHTML = `<p>エラー: ${e}</p>`));
  });
};
