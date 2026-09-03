// modules/panel-web-search.js — 企業/物件検索パネル(README 4.3 panel-web-search.js相当)
// POST /api/company/search, /api/property/search → 検索結果一覧
//
// README 6.1節の設計原則(レガシー側はAI-Sync Bridgeの存在を知らない)により、フォーム
// への書き込みはユーザーの明示的な合意(=ボタンクリック)なしには絶対に行わない。
// 「登録用データを作る」で /company/register 等がレガシーフォームのフィールド名
// (Name/Tel/...)に正規化したJSONを作り、それをそのまま表示する。
// 2026-08-20: それに加えて「新規登録ページを開いて自動入力」ボタンを追加した。これは
// shared/auto-input-engine.js の openAndFill() を使い、レガシーの新規登録ページを
// 新しいタブで開いてフィールドに値を書き込むところまでは自動化するが、送信(submit)は
// 絶対に行わない — 内容の確認とレガシー画面上の送信ボタン押下は必ずユーザーが行う。
//
// 2026-08-30: instance("erp"|"dealer", shared/config-base.js)によって機能そのものを
// 出し分けるようにした。ERPとdealerでソースは完全に共有(auto-input-engine.jsと同じ
// 「共通コード・データ駆動」の方針)しつつ、以下2点が業態で異なる:
//   - 物件検索: demo-legacy-system-dealer にはPropertyエンティティ自体が存在せず
//     (整備/車検=ServiceOrderに置換済み)、対応する新規登録フォームも無いため、
//     dealerでは物件検索タブごと非表示にする(存在しない業務への誘導を避ける)。
//   - 会社検索: dealerのCustomerフォームは氏名/運転免許証番号等の個人向け項目のみで
//     資本金/業種等の法人項目が無いため、「実在する企業」を検索する機能の登録先は
//     Customerではなく仕入先(Supplier=オークション会場/下取り仲介業者)に向ける。
//     entry_entity は ai-api-server の CompanySearchService(instance分岐済み)が
//     レスポンスで返す値をそのまま使い、フロント側でinstanceからの再導出はしない
//     (単一の判断元をサーバー側に置く)。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.websearch = function renderWebSearchPanel(el, ctx) {
  const isDealer = ctx.INSTANCE === "dealer";
  const companyLabel = isDealer ? "仕入先検索" : "会社検索";
  const companyPlaceholder = isDealer ? "仕入先名/業種等のキーワード" : "会社名/業種等のキーワード";
  const contactLabel = isDealer ? "担当者" : "代表者";

  el.innerHTML = `
    <div class="aisb-subtabs">
      <button class="aisb-subtab active" data-sub="company">${companyLabel}</button>
      ${isDealer ? "" : `<button class="aisb-subtab" data-sub="property">物件検索</button>`}
    </div>
    <div class="aisb-subpanel active" data-sub="company">
      <div class="aisb-inline-row">
        <input type="text" id="aisb-ws-company-kw" placeholder="${companyPlaceholder}" />
        <button id="aisb-ws-company-run">検索</button>
      </div>
      <div id="aisb-ws-company-result"></div>
    </div>
    ${
      isDealer
        ? ""
        : `<div class="aisb-subpanel" data-sub="property">
      <div class="aisb-inline-row">
        <input type="text" id="aisb-ws-property-kw" placeholder="物件名/エリア等のキーワード" />
        <button id="aisb-ws-property-run">検索</button>
      </div>
      <div id="aisb-ws-property-result"></div>
    </div>`
    }
  `;

  el.querySelectorAll(".aisb-subtab").forEach((tab) => {
    tab.addEventListener("click", () => {
      el.querySelectorAll(".aisb-subtab").forEach((t) => t.classList.toggle("active", t === tab));
      el.querySelectorAll(".aisb-subpanel").forEach((p) => p.classList.toggle("active", p.dataset.sub === tab.dataset.sub));
    });
  });

  // 検索結果オブジェクト自体はイベントリスナー側でクロージャ経由に渡す
  // (属性へのJSON埋め込みはエスケープが煩雑なため、ここではボタンの外枠のみ用意する)。
  function renderRegisterBtn() {
    return `<div class="aisb-btn-row">
        <button class="aisb-ws-register-btn aisb-btn-secondary">登録用データを作る</button>
        <button class="aisb-ws-autofill-btn aisb-btn-secondary" style="display:none">新規登録ページを開いて自動入力</button>
      </div>
      <pre class="aisb-ws-normalized" style="display:none"></pre>
      <p class="aisb-ws-autofill-status" style="display:none"></p>`;
  }

  // entryEntity: "Customer" | "Supplier" | "Property" — レガシー新規登録ページのURLを
  // 出し分ける。会社検索側は /company/register のレスポンス(entry_entity)がサーバー側の
  // instance判定をそのまま返すのでそれを使い、物件検索側は元々ERP専用機能のため固定。
  // 実際にタブを開いて書き込むのは openAndFill()。
  // 「登録用データを作る」は同じカード内で何度でも押し直せるため、押すたびにここが
  // 呼ばれても click リスナーが多重登録されないよう、最新データは要素のプロパティに
  // 保持し、リスナー登録自体は初回のみ行う。
  function wireAutofillBtn(card, entryEntity, normalizedData) {
    const autofillBtn = card.querySelector(".aisb-ws-autofill-btn");
    const statusEl = card.querySelector(".aisb-ws-autofill-status");
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
            (skipped.length ? ` 未入力: ${skipped.join(", ")}(値が不明なため空欄のままです)。` : "") +
            " 内容を確認のうえ、開いたタブ側で保存してください(自動送信はしていません)。";
        })
        .catch((e) => {
          statusEl.textContent = `⚠ 自動入力に失敗しました: ${e.message || e}`;
        });
    });
  }

  // source="opencode-websearch" なら実際にWeb検索した結果、"mock"なら擬似データ。
  // 2026-08-20: opencode CLIのwebsearchツールで実検索するようになったため、
  // ユーザーが実データか擬似データかを一目で区別できるようバッジを出す。
  function renderSourceNote(source) {
    if (source === "opencode-websearch") {
      return `<p class="aisb-ws-source aisb-ws-source-real">🌐 Web検索による実データ(内容は必ず裏取りしてください)</p>`;
    }
    if (source === "mock") {
      return `<p class="aisb-ws-source aisb-ws-source-mock">⚠ デモ用の擬似データ(実在の情報ではありません)</p>`;
    }
    return "";
  }

  function wireCompany() {
    const resultEl = el.querySelector("#aisb-ws-company-result");
    el.querySelector("#aisb-ws-company-run").addEventListener("click", () => {
      const keyword = el.querySelector("#aisb-ws-company-kw").value.trim();
      if (!keyword) return;
      resultEl.textContent = "検索中...";
      ctx
        .postJson(`${ctx.API_BASE}/api/company/search`, { keyword })
        .then((data) => {
          const results = data.results || [];
          resultEl.innerHTML =
            renderSourceNote(data.source) +
            (results
              .map(
                (r, i) => `<div class="aisb-card" data-idx="${i}">
              <b>${ctx.escapeHtml(r.name)}</b>${r.industry ? ` <span class="aisb-badge">${ctx.escapeHtml(r.industry)}</span>` : ""}<br>
              ${contactLabel}: ${ctx.escapeHtml(r.representative || "-")} / TEL: ${ctx.escapeHtml(r.tel || "-")}<br>
              住所: ${ctx.escapeHtml(r.address || "-")}<br>
              ${renderRegisterBtn()}
            </div>`
              )
              .join("") || "<p>該当する会社が見つかりませんでした</p>");
          resultEl.querySelectorAll(".aisb-ws-register-btn").forEach((btn, i) => {
            btn.addEventListener("click", () => {
              // btnはaisb-btn-row divの中、preはそのdivの兄弟要素なので
              // btn.nextElementSibling(常にnull)ではなくカード全体から探す。
              const pre = btn.closest(".aisb-card").querySelector(".aisb-ws-normalized");
              ctx
                .postJson(`${ctx.API_BASE}/api/company/register`, { company_data: results[i] })
                .then((res) => {
                  pre.textContent = JSON.stringify(res.normalized, null, 2);
                  pre.style.display = "block";
                  wireAutofillBtn(btn.closest(".aisb-card"), res.entry_entity || "Customer", res.normalized);
                })
                .catch((e) => alert(`エラー: ${e}`));
            });
          });
        })
        .catch((e) => (resultEl.innerHTML = `<p>エラー: ${e}</p>`));
    });
  }

  function wireProperty() {
    const resultEl = el.querySelector("#aisb-ws-property-result");
    el.querySelector("#aisb-ws-property-run").addEventListener("click", () => {
      const keyword = el.querySelector("#aisb-ws-property-kw").value.trim();
      if (!keyword) return;
      resultEl.textContent = "検索中...";
      ctx
        .postJson(`${ctx.API_BASE}/api/property/search`, { keyword })
        .then((data) => {
          const results = data.results || [];
          resultEl.innerHTML =
            renderSourceNote(data.source) +
            (results
              .map(
                (r, i) => `<div class="aisb-card" data-idx="${i}">
              <b>${ctx.escapeHtml(r.name)}</b><br>
              住所: ${ctx.escapeHtml(r.address || "-")} / 築年: ${ctx.escapeHtml(r.built_date || "-")}<br>
              価格: ${r.price != null ? `${r.price.toLocaleString()}円` : "-"} / 賃料: ${r.monthly_rent != null ? `${r.monthly_rent.toLocaleString()}円/月` : "-"}<br>
              ${renderRegisterBtn()}
            </div>`
              )
              .join("") || "<p>該当する物件が見つかりませんでした</p>");
          resultEl.querySelectorAll(".aisb-ws-register-btn").forEach((btn, i) => {
            btn.addEventListener("click", () => {
              const pre = btn.closest(".aisb-card").querySelector(".aisb-ws-normalized");
              ctx
                .postJson(`${ctx.API_BASE}/api/property/register`, { property_data: results[i] })
                .then((res) => {
                  pre.textContent = JSON.stringify(res.normalized, null, 2);
                  pre.style.display = "block";
                  wireAutofillBtn(btn.closest(".aisb-card"), "Property", res.normalized);
                })
                .catch((e) => alert(`エラー: ${e}`));
            });
          });
        })
        .catch((e) => (resultEl.innerHTML = `<p>エラー: ${e}</p>`));
    });
  }

  wireCompany();
  if (!isDealer) wireProperty();
};
