// modules/panel-conv-input.js — 自然言語入力パネル(README 4.3 panel-conv-input.js相当)
// POST /api/conversational-input(message, targetScreen, screenContext) → フィールドマッピング
//
// 2026-09-01: panel-nlsql.js(AI検索)の「サンプル(chip)をワンクリックで入力→即実行」導線と、
// panel-web-search.js(仕入先検索)/panel-ocr.js の「登録用データを作る→新規登録ページを
// 開いて自動入力」導線を、この画面にも展開した。
// 従来コメントには「shared/auto-input-engine.js が未実装のプレースホルダ」とあったが、
// 2026-08-20時点で実装済み(仕入先検索/OCRから実際に利用中)のため、この画面だけ未対応の
// ままにしておく理由はない。自動入力先の name 属性正規化はサーバー側
// ai-api-server/app/services/conversational_input_service.py の register()
// (SCREEN_FIELD_SYNONYMS)が単一の判断元。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

const CI_SCREENS = [
  { id: "order-input", label: "受注入力" },
  { id: "customer-register", label: "顧客登録" },
  { id: "estimate-mgmt", label: "見積管理" },
  { id: "invoice-mgmt", label: "請求管理" },
  { id: "supplier-mgmt", label: "仕入先管理" },
];

// 2026-08-30/09-01: 例文はinstanceによって取引実体が異なる(erp=法人間のBtoB発注、
// dealer=個人客への車両販売)ため分岐する。web_search_service.pyのCUSTOMER_FIELDS分岐/
// panel-nlsql.jsのGENERATE_PRESETS_BY_INSTANCEと同じ「実データに合わせる」方針。
// 画面(target_screen)ごとに1〜2件、chipクリックでテキストエリアに反映後そのまま実行する。
const CI_EXAMPLES_BY_INSTANCE = {
  erp: {
    "order-input": ["山田商事にポンプA-100を3個、単価12,000円、来週納品で受注したい"],
    "customer-register": ["サンプル商事株式会社、TEL 03-1234-5678、住所は東京都千代田区千代田1-1、与信限度額500万円で新規顧客登録したい"],
    "estimate-mgmt": ["山田商事にポンプA-100を5個、来月末まで有効な見積を作りたい"],
    "invoice-mgmt": ["山田商事宛に金額80万円、支払期日は来月末で請求を作成したい"],
    "supplier-mgmt": ["サンプル物流株式会社、TEL 06-1111-2222、担当者は佐藤さん、与信枠300万円で仕入先登録したい"],
  },
  dealer: {
    "order-input": ["山田太郎様にトヨタ プリウスを1台、来月納車で受注したい"],
    "customer-register": ["山田太郎様、TEL 090-1234-5678、住所は大阪府大阪市、与信限度額200万円で新規顧客登録したい"],
    "estimate-mgmt": ["山田太郎様にトヨタ プリウスの見積を来月末まで有効で作りたい"],
    "invoice-mgmt": ["山田太郎様宛に金額250万円、支払期日は来月末で請求を作成したい"],
    "supplier-mgmt": ["サンプルオークション会場、TEL 06-2222-3333、担当者は鈴木さん、与信枠500万円で仕入先登録したい"],
  },
};

window.AISB.panels.convinput = function renderConvInputPanel(el, ctx) {
  const examples = CI_EXAMPLES_BY_INSTANCE[ctx.INSTANCE] || CI_EXAMPLES_BY_INSTANCE.erp;

  el.innerHTML = `
    <div class="aisb-inline-row">
      <select id="aisb-ci-screen">
        ${CI_SCREENS.map((s) => `<option value="${s.id}">${s.label}</option>`).join("")}
      </select>
    </div>
    <div id="aisb-ci-presets" class="aisb-chip-row"></div>
    <textarea id="aisb-ci-msg" style="width:100%;min-height:56px;padding:6px 8px;border:1px solid #ccc;border-radius:4px;font-size:12px;font-family:inherit;resize:vertical;margin-bottom:6px"></textarea>
    <div class="aisb-btn-row">
      <button id="aisb-ci-run">解析</button>
    </div>
    <div id="aisb-ci-result"></div>
  `;
  const screenSelect = el.querySelector("#aisb-ci-screen");
  const presetsEl = el.querySelector("#aisb-ci-presets");
  const msgEl = el.querySelector("#aisb-ci-msg");
  const resultEl = el.querySelector("#aisb-ci-result");
  let conversationId = crypto.randomUUID();

  // AI検索(panel-nlsql.js)と同じ「chipクリック→テキスト反映→即実行」。
  function renderPresets() {
    const list = examples[screenSelect.value] || [];
    presetsEl.innerHTML = list
      .map((q, i) => `<button type="button" class="aisb-chip" data-i="${i}">${ctx.escapeHtml(q)}</button>`)
      .join("");
    msgEl.placeholder = list[0] ? `例: ${list[0]}` : "";
    presetsEl.querySelectorAll(".aisb-chip").forEach((btn, i) => {
      btn.addEventListener("click", () => {
        msgEl.value = list[i];
        run();
      });
    });
  }
  screenSelect.addEventListener("change", renderPresets);
  renderPresets();

  // 仕入先検索(panel-web-search.js)/OCR(panel-ocr.js)と同じ構造の
  // 「登録用データを作る→新規登録ページを開いて自動入力」。
  function renderRegisterArea() {
    return `<div class="aisb-btn-row">
        <button class="aisb-ci-register-btn aisb-btn-secondary">登録用データを作る</button>
        <button class="aisb-ci-autofill-btn aisb-btn-secondary" style="display:none">新規登録ページを開いて自動入力</button>
      </div>
      <pre class="aisb-ci-normalized" style="display:none"></pre>
      <p class="aisb-ci-autofill-status" style="display:none"></p>`;
  }

  function wireAutofillBtn(area, entryEntity, normalizedData) {
    const autofillBtn = area.querySelector(".aisb-ci-autofill-btn");
    const statusEl = area.querySelector(".aisb-ci-autofill-status");
    autofillBtn.style.display = "inline-block";
    autofillBtn._aisbNormalizedData = normalizedData;
    if (autofillBtn.dataset.wired) return;
    autofillBtn.dataset.wired = "1";
    autofillBtn.addEventListener("click", () => {
      const entryUrl = `${ctx.LEGACY_ORIGIN}/${entryEntity}/Entry`;
      statusEl.style.display = "block";
      statusEl.textContent = "登録ページを開いています...";
      window.AISB.autoInputEngine
        .openAndFill(entryUrl, autofillBtn._aisbNormalizedData)
        .then(({ filled, skipped }) => {
          statusEl.textContent =
            `✅ ${filled.length}項目を自動入力しました(${filled.join(", ")})。` +
            (skipped.length ? ` 未入力: ${skipped.join(", ")}(値が不明、または画面上に対応する項目が無いため空欄のままです)。` : "") +
            " 内容を確認のうえ、開いたタブ側で保存してください(自動送信はしていません)。";
        })
        .catch((e) => {
          statusEl.textContent = `⚠ 自動入力に失敗しました: ${e.message || e}`;
        });
    });
  }

  async function run() {
    const targetScreen = screenSelect.value;
    const message = msgEl.value.trim();
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
        <div id="aisb-ci-register-area"></div>
      `;

      if (mappings.length) {
        const registerArea = resultEl.querySelector("#aisb-ci-register-area");
        registerArea.innerHTML = renderRegisterArea();
        registerArea.querySelector(".aisb-ci-register-btn").addEventListener("click", () => {
          const pre = registerArea.querySelector(".aisb-ci-normalized");
          const fields = Object.fromEntries(mappings.map((m) => [m.field, m.value]));
          ctx
            .postJson(`${ctx.API_BASE}/api/conversational-input/register`, { fields, target_screen: targetScreen })
            .then((res) => {
              pre.textContent = JSON.stringify(res.normalized, null, 2);
              pre.style.display = "block";
              wireAutofillBtn(registerArea, res.entry_entity, res.normalized);
            })
            .catch((e) => alert(`エラー: ${e}`));
        });
      }
    } catch (e) {
      resultEl.innerHTML = `<p>エラー: ${e}</p>`;
    }
  }

  el.querySelector("#aisb-ci-run").addEventListener("click", run);
};
