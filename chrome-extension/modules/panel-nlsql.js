// modules/panel-nlsql.js — AI検索パネル(自然言語→構造化フィルタ検索, 仕様5.4.11差分実装)
//                          + 定型クロス分析レポート(与信リスク/在庫逼迫/滞留債権)
//
// 仕様書5.4.11は「AIが生成したSQLを直接実行する」方式を規定しているが、データ層が
// 実SQLエンジンを持たないインメモリdict(demo-legacy-system/data.py)であり、かつ
// 生成AIの出力をそのまま実行するインジェクション/誤操作リスクを避けるため、
// ai-api-server側(POST /api/nlsql/query)で「構造化フィルタ(JSON)への変換→
// ホワイトリスト検証→安全な評価」という方式に置き換えている。このパネルは
// そのAPIを呼び、AIが実際に適用した条件(applied_filter)を透明性のため表示する。
//
// 単一エンティティのフィルタ検索だけでは「与信限度額」「在庫の逼迫」「坏账(滞留債権)」
// のような実業務で頻度の高い分析はできない(複数エンティティの突き合わせが必要)。
// そのため ai-api-server/app/services/cross_analysis_service.py が算出した定型レポート
// (GET /api/cross-analysis/{report})をボタン一発で呼び出し、チャート+集計+明細を
// 表示するセクションをこのパネルの上部に追加した。算出ロジック自体はAI非依存で、
// AI解釈コメントは既存のforecast/reorder等と同じ opt-in ボタン(ctx.runInsight)。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

// クロス分析レポートの明細テーブルで表示する列(狭いサイドバー幅に収めるための
// 抜粋。cross_analysis_service.pyのrows全フィールドのうち代表的なものだけを選ぶ、
// LEGACY_ENTITIESのcols指定と同じ考え方)。
const XA_TABLE_COLS = {
  "credit-risk": ["CustomerName", "CreditLimit", "Exposure", "UsageRatio", "RiskLevel"],
  "stock-tension": ["ProductName", "Stock", "SafetyStock", "DaysOfStockRemaining", "Urgent"],
  "bad-debt": ["InvoiceId", "CustomerName", "TotalAmount", "DueDate", "DaysOverdue"],
};

// summary(dict)のキー→日本語ラベル。定義がないキーはそのままキー名を表示する。
const XA_SUMMARY_LABELS = {
  customer_count: "顧客数", exceeded_count: "限度額超過", warning_count: "警戒(80%以上)",
  total_exposure: "エクスポージャー合計(円)", total_limit: "与信限度額合計(円)",
  product_count: "商品数", urgent_count: "逼迫商品数", below_safety_count: "安全在庫割れ数",
  overdue_invoice_count: "延滞請求件数", overdue_total_amount: "延滞金額合計(円)",
  affected_customer_count: "対象顧客数",
  // AI自動生成レポート(generate)のsummaryキー
  matched_rows: "対象件数", group_count: "グループ数", primary_entity: "主エンティティ",
  secondary_entity: "副エンティティ", agg: "集計方法",
};

// AI自動生成レポートのよく使う質問例(業種横断・在庫×入出庫等、定型3レポートでは
// カバーしていない切り口の例を挙げておく。ワンクリックで生成→即実行)。
const GENERATE_PRESETS = [
  "業種別の与信限度額合計を高い順に",
  "延滞している請求の金額を顧客の業種別に合計",
  "商品カテゴリ別の入庫数量を多い順に",
  "仕入先ごとの発注金額合計を高い順に10件",
  "顧客ごとの受注件数を多い順に",
];

// エンティティごとのよく使う質問文プリセット。実データ(demo-legacy-system/data.py)の
// 実在するステータス値・カテゴリ値・項目名に合わせてあるため、そのままクリック一発で
// ヒットする(=AIが値を捏造して0件になる事故を防ぐ意味もある)。ボタン(chip)クリックで
// テキストエリアに反映した上でそのままAI検索を実行する。
const QUERY_PRESETS = {
  Customer: ["与信限度額が100万円を超える顧客を、限度額の高い順に5件", "与信限度額が低い順に10件"],
  Order: ["出荷済の受注", "受注金額が50万円以上の受注を金額の高い順に10件", "キャンセルされた受注"],
  Product: ["在庫数が10個未満の商品", "電子部品カテゴリの商品を単価の高い順に"],
  Supplier: ["工具カテゴリの仕入先"],
  Employee: ["営業部の従業員", "部長職の従業員"],
  Estimate: ["承認された見積", "失注した見積"],
  Invoice: ["延滞している請求", "未払いの請求を金額の高い順に"],
  PurchaseOrder: ["発注中の発注", "キャンセルされた発注"],
  InventoryTransaction: ["出庫の在庫トランザクション"],
  GoodsReceipt: ["入荷数量が50個以上の入荷"],
  Property: ["価格が5000万円以上の物件"],
  ArAp: ["売掛金の残高が高い順に10件", "買掛金の一覧"],
  Profit: ["粗利率が低い順に10件", "粗利額が高い順に5件"],
};

window.AISB.panels.nlsql = function renderNlsqlPanel(el, ctx) {
  const { escapeHtml, LEGACY_ENTITIES } = ctx;
  const detected = ctx.detectLegacyContext();

  el.innerHTML = `
    <div class="aisb-section-title">定型クロス分析レポート(複数データの横断集計)</div>
    <div id="aisb-xa-buttons" class="aisb-btn-row">読込中...</div>
    <div id="aisb-xa-result"></div>

    <div class="aisb-section-title">AIレポート自動生成(横断集計をAIが都度組み立て)</div>
    <div class="aisb-hint">上の3レポートに無い切り口も、質問文からAIが「集計元データ・結合・グループ化・
      集計方法」を組み立てて実行します(結合は許可された組み合わせのみ、生SQLは使いません)。</div>
    <div id="aisb-gen-presets" class="aisb-chip-row"></div>
    <textarea id="aisb-gen-q" placeholder="例: 延滞している請求の金額を顧客の業種別に合計"></textarea>
    <div class="aisb-btn-row">
      <button id="aisb-gen-run">AIでレポート生成</button>
    </div>
    <div id="aisb-gen-result"></div>

    <div class="aisb-section-title">AI検索(自然言語 → 構造化フィルタ)</div>
    <div class="aisb-inline-row">
      <select id="aisb-nlsql-entity">
        ${LEGACY_ENTITIES.map((e) => `<option value="${e.id}">${e.label}</option>`).join("")}
      </select>
    </div>
    <div id="aisb-nlsql-presets" class="aisb-chip-row"></div>
    <textarea id="aisb-nlsql-q" placeholder="例: 与信限度額が100万円を超える顧客を、限度額の高い順に5件"></textarea>
    <div class="aisb-btn-row">
      <button id="aisb-nlsql-run">AIで検索</button>
    </div>
    <div id="aisb-nlsql-result"></div>
  `;

  initCrossAnalysis(el, ctx);
  initDynamicAnalysis(el, ctx);

  const selectEl = el.querySelector("#aisb-nlsql-entity");
  const presetsEl = el.querySelector("#aisb-nlsql-presets");
  const qEl = el.querySelector("#aisb-nlsql-q");
  const runBtn = el.querySelector("#aisb-nlsql-run");
  const resultEl = el.querySelector("#aisb-nlsql-result");

  if (detected && LEGACY_ENTITIES.some((e) => e.id === detected.entity)) {
    selectEl.value = detected.entity;
  }

  function metaFor(entityId) {
    return LEGACY_ENTITIES.find((e) => e.id === entityId) || LEGACY_ENTITIES[0];
  }

  function renderPresets() {
    const presets = QUERY_PRESETS[selectEl.value] || [];
    presetsEl.innerHTML = presets
      .map((q, i) => `<button type="button" class="aisb-chip" data-i="${i}">${escapeHtml(q)}</button>`)
      .join("");
    presetsEl.querySelectorAll(".aisb-chip").forEach((btn, i) => {
      btn.addEventListener("click", () => {
        qEl.value = presets[i];
        run();
      });
    });
  }
  selectEl.addEventListener("change", renderPresets);
  renderPresets();

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

// ---------------------------------------------------------------------
// 定型クロス分析レポート(与信リスク/在庫逼迫/滞留債権)
// レポート一覧はハードコードせず GET /api/cross-analysis/reports から取得する
// (cross_analysis_service.py の REPORTS が唯一の情報源。フロント側で二重管理しない)。
// ---------------------------------------------------------------------
function initCrossAnalysis(el, ctx) {
  const { escapeHtml, renderRankedBarChart } = ctx;
  const buttonsEl = el.querySelector("#aisb-xa-buttons");
  const resultEl = el.querySelector("#aisb-xa-result");

  fetch(`${ctx.API_BASE}/api/cross-analysis/reports`)
    .then((r) => r.json())
    .then((reports) => {
      buttonsEl.innerHTML = reports
        .map((r) => `<button type="button" class="aisb-btn-secondary" data-report="${r.id}">${escapeHtml(r.label)}</button>`)
        .join("");
      buttonsEl.querySelectorAll("button").forEach((btn) => {
        btn.addEventListener("click", () => runCrossAnalysis(btn.dataset.report, btn));
      });
    })
    .catch((e) => (buttonsEl.innerHTML = `<p>エラー: ${escapeHtml(String(e))}</p>`));

  function summaryBadges(summary) {
    return Object.entries(summary || {})
      .map(([k, v]) => `<span class="aisb-badge">${escapeHtml(XA_SUMMARY_LABELS[k] || k)}: ${escapeHtml(v)}</span>`)
      .join(" ");
  }

  async function runCrossAnalysis(reportId, btn) {
    buttonsEl.querySelectorAll("button").forEach((b) => (b.disabled = true));
    const prevLabel = btn.textContent;
    btn.textContent = "集計中...";
    resultEl.innerHTML = "";
    try {
      const data = await (await fetch(`${ctx.API_BASE}/api/cross-analysis/${reportId}`)).json();
      const warningsHtml = (data.warnings || [])
        .map((w) => `<div class="aisb-card aisb-warning-card">${escapeHtml(w)}</div>`)
        .join("");
      const cols = (XA_TABLE_COLS[reportId] || Object.keys((data.rows || [])[0] || {})).filter(
        (c) => data.rows[0] && c in data.rows[0]
      );
      const tableHtml = data.rows && data.rows.length
        ? `<table class="aisb-table">
            <thead><tr>${cols.map((c) => `<th>${escapeHtml(c)}</th>`).join("")}</tr></thead>
            <tbody>
              ${data.rows
                .slice(0, 50)
                .map((row) => `<tr>${cols.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("")}</tr>`)
                .join("")}
            </tbody>
          </table>`
        : "<p>該当データがありません</p>";

      resultEl.innerHTML = `
        <div class="aisb-card">
          <b>${escapeHtml(data.label)}</b><br>
          ${summaryBadges(data.summary)}
        </div>
        ${warningsHtml}
        <div class="aisb-chart aisb-hbar-chart">${renderRankedBarChart(data.chart)}</div>
        <div class="aisb-btn-row">
          <button type="button" id="aisb-xa-insight-btn" class="aisb-btn-secondary">AIで解釈する</button>
        </div>
        <div id="aisb-xa-insight"></div>
        ${tableHtml}
      `;
      resultEl.querySelector("#aisb-xa-insight-btn").addEventListener("click", (e) =>
        ctx.runInsight(`${ctx.API_BASE}/api/cross-analysis/${reportId}/insight`, e.target, resultEl.querySelector("#aisb-xa-insight"))
      );
    } catch (e) {
      resultEl.innerHTML = `<p>エラー: ${escapeHtml(String(e))}</p>`;
    } finally {
      buttonsEl.querySelectorAll("button").forEach((b) => (b.disabled = false));
      btn.textContent = prevLabel;
    }
  }
}

// ---------------------------------------------------------------------
// AIレポート自動生成(汎用集計エンジン、GET /api/cross-analysis/generate)
// 定型3レポートと違い、どのエンティティを・どう結合し・何を軸に集計するかを
// 質問文からAIがJSON(spec)として都度生成する。結合できる組み合わせは
// ai-api-server/app/services/dynamic_analysis_service.py の JOIN_GRAPH に固定
// されており(生SQL/eval不使用)、specはレスポンスにそのまま含まれるので
// 「AIが実際に何を集計したか」を透明表示できる(nlsqlのapplied_filterと同じ思想)。
// ---------------------------------------------------------------------
function initDynamicAnalysis(el, ctx) {
  const { escapeHtml, renderRankedBarChart } = ctx;
  const presetsEl = el.querySelector("#aisb-gen-presets");
  const qEl = el.querySelector("#aisb-gen-q");
  const runBtn = el.querySelector("#aisb-gen-run");
  const resultEl = el.querySelector("#aisb-gen-result");

  presetsEl.innerHTML = GENERATE_PRESETS.map(
    (q, i) => `<button type="button" class="aisb-chip" data-i="${i}">${escapeHtml(q)}</button>`
  ).join("");
  presetsEl.querySelectorAll(".aisb-chip").forEach((btn, i) => {
    btn.addEventListener("click", () => {
      qEl.value = GENERATE_PRESETS[i];
      run();
    });
  });

  function summaryBadges(summary) {
    return Object.entries(summary || {})
      .map(([k, v]) => `<span class="aisb-badge">${escapeHtml(XA_SUMMARY_LABELS[k] || k)}: ${escapeHtml(v)}</span>`)
      .join(" ");
  }

  function fieldRefText(ref) {
    if (!ref) return "";
    return ref.scope === "secondary" ? `(副)${ref.field}` : ref.field;
  }

  function renderSpecSummary(spec) {
    if (!spec) return "";
    const parts = [`主エンティティ: ${spec.primary_entity}`];
    if (spec.secondary_entity) parts.push(`結合: ${spec.secondary_entity}`);
    if (spec.filters && spec.filters.length) {
      parts.push(
        "条件: " + spec.filters.map((f) => `${fieldRefText(f)} ${f.op} ${JSON.stringify(f.value)}`).join(" かつ ")
      );
    }
    parts.push(`グループ化: ${fieldRefText(spec.group_by)}`);
    parts.push(`集計: ${spec.agg}${spec.metric ? `(${fieldRefText(spec.metric)})` : ""}`);
    return parts.join(" / ");
  }

  async function run() {
    const question = qEl.value.trim();
    if (!question) {
      resultEl.innerHTML = "<p>質問を入力してください</p>";
      return;
    }
    runBtn.disabled = true;
    const prevLabel = runBtn.textContent;
    runBtn.textContent = "AIが集計条件を組み立て中...(数十秒かかることがあります)";
    resultEl.innerHTML = "";
    try {
      const data = await ctx.postJson(`${ctx.API_BASE}/api/cross-analysis/generate`, { question });
      const warningsHtml = (data.warnings || [])
        .map((w) => `<div class="aisb-card aisb-warning-card">${escapeHtml(w)}</div>`)
        .join("");
      const specHtml = `<div class="aisb-filter-summary">${escapeHtml(renderSpecSummary(data.spec))}</div>`;

      if (!data.rows.length) {
        resultEl.innerHTML = `${specHtml}${warningsHtml}<p>該当データがありません</p>`;
        return;
      }
      const tableHtml = `
        <table class="aisb-table">
          <thead><tr><th>グループ</th><th>集計値</th><th>件数</th></tr></thead>
          <tbody>
            ${data.rows
              .map((r) => `<tr><td>${escapeHtml(r.group)}</td><td>${escapeHtml(r.value)}</td><td>${escapeHtml(r.matched_count)}</td></tr>`)
              .join("")}
          </tbody>
        </table>
      `;
      resultEl.innerHTML = `
        <div class="aisb-card">
          <b>${escapeHtml(data.label)}</b><br>
          ${summaryBadges(data.summary)}
        </div>
        ${specHtml}${warningsHtml}
        <div class="aisb-chart aisb-hbar-chart">${renderRankedBarChart(data.chart)}</div>
        <div class="aisb-btn-row">
          <button type="button" id="aisb-gen-insight-btn" class="aisb-btn-secondary">AIで解釈する</button>
        </div>
        <div id="aisb-gen-insight"></div>
        ${tableHtml}
      `;
      resultEl.querySelector("#aisb-gen-insight-btn").addEventListener("click", (e) =>
        ctx.runInsight(
          `${ctx.API_BASE}/api/cross-analysis/generate/insight?question=${encodeURIComponent(question)}`,
          e.target,
          resultEl.querySelector("#aisb-gen-insight")
        )
      );
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
}
