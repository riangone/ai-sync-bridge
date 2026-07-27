// modules/panel-nlsql.js — AI検索パネル(自然言語→構造化フィルタ検索, 仕様5.4.11差分実装)
//
// 仕様書5.4.11は「AIが生成したSQLを直接実行する」方式を規定しているが、データ層が
// 実SQLエンジンを持たないインメモリdict(demo-legacy-system/data.py)であり、かつ
// 生成AIの出力をそのまま実行するインジェクション/誤操作リスクを避けるため、
// ai-api-server側(POST /api/nlsql/query)で「構造化フィルタ(JSON)への変換→
// ホワイトリスト検証→安全な評価」という方式に置き換えている。このパネルは
// そのAPIを呼び、AIが実際に適用した条件(applied_filter)を透明性のため表示する。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.nlsql = function renderNlsqlPanel(el, ctx) {
  const { escapeHtml, LEGACY_ENTITIES } = ctx;
  const detected = ctx.detectLegacyContext();

  el.innerHTML = `
    <div class="aisb-section-title">AI検索(自然言語 → 構造化フィルタ)</div>
    <div class="aisb-inline-row">
      <select id="aisb-nlsql-entity">
        ${LEGACY_ENTITIES.map((e) => `<option value="${e.id}">${e.label}</option>`).join("")}
      </select>
    </div>
    <textarea id="aisb-nlsql-q" placeholder="例: 与信限度額が100万円を超える顧客を、限度額の高い順に5件"></textarea>
    <div class="aisb-btn-row">
      <button id="aisb-nlsql-run">AIで検索</button>
    </div>
    <div id="aisb-nlsql-result"></div>
  `;

  const selectEl = el.querySelector("#aisb-nlsql-entity");
  const qEl = el.querySelector("#aisb-nlsql-q");
  const runBtn = el.querySelector("#aisb-nlsql-run");
  const resultEl = el.querySelector("#aisb-nlsql-result");

  if (detected && LEGACY_ENTITIES.some((e) => e.id === detected.entity)) {
    selectEl.value = detected.entity;
  }

  function metaFor(entityId) {
    return LEGACY_ENTITIES.find((e) => e.id === entityId) || LEGACY_ENTITIES[0];
  }

  function renderFilterSummary(applied) {
    const parts = [];
    if (applied.conditions.length) {
      const joiner = applied.logic === "or" ? " または " : " かつ ";
      parts.push(applied.conditions.map((c) => `${c.field} ${c.op} ${JSON.stringify(c.value)}`).join(joiner));
    } else {
      parts.push("(絞り込み条件なし)");
    }
    if (applied.sort) parts.push(`並び替え: ${applied.sort.field} ${applied.sort.dir}`);
    parts.push(`上限: ${applied.limit}件`);
    return parts.join(" / ");
  }

  async function run() {
    const entity = selectEl.value;
    const question = qEl.value.trim();
    if (!question) {
      resultEl.innerHTML = "<p>質問を入力してください</p>";
      return;
    }
    runBtn.disabled = true;
    const prevLabel = runBtn.textContent;
    runBtn.textContent = "AIが条件を解釈中...(数秒〜十数秒)";
    resultEl.innerHTML = "";
    try {
      const data = await ctx.postJson(`${ctx.API_BASE}/api/nlsql/query`, { entity, question });
      const meta = metaFor(entity);
      const warningsHtml = (data.warnings || [])
        .map((w) => `<div class="aisb-card aisb-warning-card">${escapeHtml(w)}</div>`)
        .join("");
      const filterHtml = `<div class="aisb-filter-summary">${escapeHtml(renderFilterSummary(data.applied_filter))}</div>`;
      const badgeHtml = `<div class="aisb-badge">${data.count}件 / 全${data.total_scanned}件中 (AI: ${escapeHtml(data.provider)})</div>`;

      if (!data.rows.length) {
        resultEl.innerHTML = `${filterHtml}${warningsHtml}${badgeHtml}<p>該当データがありません</p>`;
        return;
      }
      // 行に実在するキーのうち、業務データパネルと同じ列定義(meta.cols)を優先して表示する。
      // AIが選んだ条件のfieldがcolsに含まれない場合でも、データ自体はそのまま返っている。
      const cols = meta.cols.filter((c) => c in data.rows[0]);
      const displayCols = cols.length ? cols : Object.keys(data.rows[0]).slice(0, 6);
      resultEl.innerHTML = `
        ${filterHtml}${warningsHtml}${badgeHtml}
        <table class="aisb-table">
          <thead><tr>${displayCols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
          <tbody>
            ${data.rows
              .map((row) => `<tr>${displayCols.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("")}</tr>`)
              .join("")}
          </tbody>
        </table>
      `;
    } catch (e) {
      resultEl.innerHTML = `<p>エラー: ${escapeHtml(String(e))}</p>`;
    } finally {
      runBtn.disabled = false;
      runBtn.textContent = prevLabel;
    }
  }

  runBtn.addEventListener("click", run);
  qEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && (e.metaKey || e.ctrlKey)) run();
  });
};
