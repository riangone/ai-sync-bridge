// modules/panel-conv-input.js — 自然言語入力パネル(README 4.3 panel-conv-input.js相当)
// POST /api/conversational-input(message, targetScreen, screenContext) → フィールドマッピング
//
// 抽出結果はマッピング一覧として表示するのみで、実フォームへの自動入力は行わない
// (shared/auto-input-engine.js が未実装のプレースホルダである理由と同じ方針。
// panel-web-search.js のコメントも参照)。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.convinput = function renderConvInputPanel(el, ctx) {
  const screens = [
    { id: "order-input", label: "受注入力" },
    { id: "customer-register", label: "顧客登録" },
    { id: "estimate-mgmt", label: "見積管理" },
    { id: "invoice-mgmt", label: "請求管理" },
    { id: "supplier-mgmt", label: "仕入先管理" },
  ];
  // 2026-08-30: 例文はinstanceによって取引実体が異なる(erp=法人間のBtoB発注、
  // dealer=個人客への車両販売)ため分岐する。web_search_service.pyのCUSTOMER_FIELDS
  // 分岐/panel-nlsql.jsのGENERATE_PRESETS_BY_INSTANCEと同じ「実データに合わせる」方針。
  const examplePlaceholder = ctx.INSTANCE === "dealer"
    ? "例: 山田太郎様にトヨタ プリウスを1台、来月納車で受注したい"
    : "例: 山田商事にポンプA-100を3個、来週納品で発注したい";
  el.innerHTML = `
    <div class="aisb-inline-row">
      <select id="aisb-ci-screen">
        ${screens.map((s) => `<option value="${s.id}">${s.label}</option>`).join("")}
      </select>
    </div>
    <textarea id="aisb-ci-msg" placeholder="${examplePlaceholder}" style="width:100%;min-height:56px;padding:6px 8px;border:1px solid #ccc;border-radius:4px;font-size:12px;font-family:inherit;resize:vertical;margin-bottom:6px"></textarea>
    <div class="aisb-btn-row">
      <button id="aisb-ci-run">解析</button>
    </div>
    <div id="aisb-ci-result"></div>
  `;
  const resultEl = el.querySelector("#aisb-ci-result");
  let conversationId = crypto.randomUUID();

  el.querySelector("#aisb-ci-run").addEventListener("click", async () => {
    const targetScreen = el.querySelector("#aisb-ci-screen").value;
    const message = el.querySelector("#aisb-ci-msg").value.trim();
    if (!message) return;
    resultEl.textContent = "解析中...";
    try {
      const data = await ctx.postJson(`${ctx.API_BASE}/api/conversational-input`, {
        message,
        target_screen: targetScreen,
        screen_context: ctx.detectLegacyContext(),
        conversation_id: conversationId,
      });
      conversationId = data.conversation_id;
      const mappings = data.input_mappings || [];
      const missing = data.missing_fields || [];
      resultEl.innerHTML = `
        <div class="aisb-card">${ctx.escapeHtml(data.response)}</div>
        <div class="aisb-badge">充足度: ${Math.round(data.confidence * 100)}%</div>
        <table class="aisb-table">
          <thead><tr><th>項目</th><th>値</th><th>信頼度</th></tr></thead>
          <tbody>${
            mappings
              .map(
                (m) => `<tr>
              <td>${ctx.escapeHtml(m.field)}</td><td>${ctx.escapeHtml(m.value)}</td>
              <td>${m.confidence === "high" ? "AI抽出" : "推定補完"}</td>
            </tr>`
              )
              .join("") || `<tr><td colspan="3">項目を抽出できませんでした</td></tr>`
          }</tbody>
        </table>
        ${
          missing.length
            ? `<div class="aisb-card aisb-warning-card">不足している項目: ${missing.map((f) => ctx.escapeHtml(f)).join(" / ")}</div>`
            : `<div class="aisb-card aisb-risk-on_track">必須項目は揃っています。内容を確認のうえ、レガシー画面へ入力してください。</div>`
        }
      `;
    } catch (e) {
      resultEl.innerHTML = `<p>エラー: ${e}</p>`;
    }
  });
};
