// modules/panel-valuation.js — 不動産仲介(demo-legacy-system-realestate)専用パネル
// erp/dealer には存在しないProperty(物件)/Viewing(内見予約)エンティティに依存する
// 3機能をまとめる(サーバー側 app/routers/realestate.py, instance!="realestate"では
// 404になるため、このパネル自体もconfig-base.jsのDEFAULT_PROFILE.panelsに
// realestate版のみ追加している):
//   1. 査定AI    — POST /api/realestate/valuation (類似物件の㎡単価統計による想定成約価格帯)
//   2. 仲介手数料 — POST /api/realestate/commission-check (宅建業法の速算式による上限チェック)
//   3. 内見重複  — GET  /api/realestate/viewing-conflicts (日程重複/エージェント過密検知、
//      inventory anomaliesと同じくAI非依存のルールベース検知なのでinsightボタンは無い)
// 1,2は集計自体はAI非依存(ルールベース)。AIの解釈は「AIで解釈する」ボタンからオプトインで
// 呼ぶ(GET /insight、他パネルと同じ設計)。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.valuation = function renderValuationPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-subtabs">
      <button class="aisb-subtab active" data-sub="valuation">査定AI</button>
      <button class="aisb-subtab" data-sub="commission">仲介手数料</button>
      <button class="aisb-subtab" data-sub="conflicts">内見重複</button>
    </div>

    <div class="aisb-subpanel active" data-sub="valuation">
      <div class="aisb-inline-row">
        <select id="aisb-val-type">
          <option value="">種別(問わず)</option>
          <option>マンション</option>
          <option>戸建て</option>
          <option>土地</option>
          <option>一棟収益</option>
        </select>
      </div>
      <div class="aisb-inline-row">
        <input type="number" id="aisb-val-building" placeholder="建物面積(㎡)" />
        <input type="number" id="aisb-val-land" placeholder="敷地面積(㎡、任意)" />
      </div>
      <div class="aisb-inline-row">
        <input type="text" id="aisb-val-address" placeholder="住所キーワード(任意、例: 渋谷)" />
        <button id="aisb-val-run">査定額を試算</button>
      </div>
      <div id="aisb-val-result"></div>
      <div class="aisb-btn-row">
        <button id="aisb-val-insight-btn" class="aisb-btn-secondary">AIで解釈する</button>
      </div>
      <div id="aisb-val-insight"></div>
    </div>

    <div class="aisb-subpanel" data-sub="commission">
      <div class="aisb-inline-row">
        <input type="number" id="aisb-com-amount" placeholder="契約金額(円)" />
      </div>
      <div class="aisb-inline-row">
        <input type="number" id="aisb-com-requested" placeholder="請求予定額(税込・任意、省略時は上限額で検査)" />
        <button id="aisb-com-run">上限をチェック</button>
      </div>
      <div id="aisb-com-result"></div>
      <div class="aisb-btn-row">
        <button id="aisb-com-insight-btn" class="aisb-btn-secondary">AIで解釈する</button>
      </div>
      <div id="aisb-com-insight"></div>
    </div>

    <div class="aisb-subpanel" data-sub="conflicts">
      <div class="aisb-btn-row">
        <button id="aisb-conf-run">内見予約の重複を検知</button>
      </div>
      <div id="aisb-conf-result"></div>
    </div>
  `;

  el.querySelectorAll(".aisb-subtab").forEach((tab) => {
    tab.addEventListener("click", () => {
      el.querySelectorAll(".aisb-subtab").forEach((t) => t.classList.toggle("active", t === tab));
      el.querySelectorAll(".aisb-subpanel").forEach((p) => p.classList.toggle("active", p.dataset.sub === tab.dataset.sub));
    });
  });

  // ---- 1. 査定AI ----
  const valResultEl = el.querySelector("#aisb-val-result");
  function valuationParams() {
    return {
      property_type: el.querySelector("#aisb-val-type").value || null,
      building_area: parseFloat(el.querySelector("#aisb-val-building").value) || null,
      land_area: parseFloat(el.querySelector("#aisb-val-land").value) || null,
      address_keyword: el.querySelector("#aisb-val-address").value || null,
    };
  }
  el.querySelector("#aisb-val-run").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    valResultEl.textContent = "試算中...";
    ctx
      .postJson(`${ctx.API_BASE}/api/realestate/valuation`, valuationParams())
      .then((data) => {
        valResultEl.innerHTML = `
          <div class="aisb-card aisb-summary-card">${ctx.escapeHtml(data.summary)}</div>
          ${
            data.comparable_count
              ? `<div class="aisb-badge">想定成約価格帯: ${Math.round(data.suggested_price_low).toLocaleString()}円 〜 ${Math.round(data.suggested_price_high).toLocaleString()}円</div>
                 <div class="aisb-badge">㎡単価 中央値: ${data.unit_price_median.toLocaleString()}円/㎡(比較対象${data.comparable_count}件)</div>
                 ${data.warnings.map((w) => `<div class="aisb-card aisb-risk-due_soon">${ctx.escapeHtml(w)}</div>`).join("")}
                 ${data.comparables
                   .map(
                     (c) => `<div class="aisb-card">
                       <b>${ctx.escapeHtml(c.name || "")}</b> <span class="aisb-badge">${ctx.escapeHtml(c.status || "")}</span><br>
                       ${ctx.escapeHtml(c.address || "")}<br>
                       価格 ${Math.round(c.price).toLocaleString()}円(㎡単価 ${c.unit_price.toLocaleString()}円/㎡)
                     </div>`
                   )
                   .join("")}`
              : ""
          }`;
      })
      .catch((err) => (valResultEl.innerHTML = `<p>エラー: ${err}</p>`))
      .finally(() => (btn.disabled = false));
  });
  el.querySelector("#aisb-val-insight-btn").addEventListener("click", (e) => {
    const p = valuationParams();
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== ""))
    ).toString();
    ctx.runInsight(`${ctx.API_BASE}/api/realestate/valuation/insight?${qs}`, e.target, el.querySelector("#aisb-val-insight"));
  });

  // ---- 2. 仲介手数料上限チェック ----
  const comResultEl = el.querySelector("#aisb-com-result");
  function commissionParams() {
    const amount = parseFloat(el.querySelector("#aisb-com-amount").value) || 0;
    const requestedRaw = el.querySelector("#aisb-com-requested").value;
    return { contract_amount: amount, requested_amount: requestedRaw ? parseFloat(requestedRaw) : null };
  }
  el.querySelector("#aisb-com-run").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    comResultEl.textContent = "チェック中...";
    ctx
      .postJson(`${ctx.API_BASE}/api/realestate/commission-check`, commissionParams())
      .then((data) => {
        comResultEl.innerHTML = `
          <div class="aisb-card ${data.over_legal_cap ? "aisb-risk-overdue" : "aisb-risk-on_track"}">
            ${ctx.escapeHtml(data.summary)}
          </div>
          <div class="aisb-badge">上限(税込): ${Math.round(data.legal_cap_incl_tax).toLocaleString()}円</div>
          <div class="aisb-badge">請求予定額: ${Math.round(data.requested_amount).toLocaleString()}円</div>`;
      })
      .catch((err) => (comResultEl.innerHTML = `<p>エラー: ${err}</p>`))
      .finally(() => (btn.disabled = false));
  });
  el.querySelector("#aisb-com-insight-btn").addEventListener("click", (e) => {
    const p = commissionParams();
    if (!p.contract_amount) {
      el.querySelector("#aisb-com-insight").innerHTML = "<p>契約金額を入力してください</p>";
      return;
    }
    const qs = new URLSearchParams(
      Object.fromEntries(Object.entries(p).filter(([, v]) => v !== null && v !== ""))
    ).toString();
    ctx.runInsight(`${ctx.API_BASE}/api/realestate/commission-check/insight?${qs}`, e.target, el.querySelector("#aisb-com-insight"));
  });

  // ---- 3. 内見(Viewing)日程重複/エージェント過密検知 ----
  const confResultEl = el.querySelector("#aisb-conf-result");
  const conflictTypeLabel = { property_double_booking: "物件の二重案内", agent_overload: "エージェント過密" };
  el.querySelector("#aisb-conf-run").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    confResultEl.textContent = "検知中...";
    fetch(`${ctx.API_BASE}/api/realestate/viewing-conflicts`)
      .then((r) => r.json())
      .then((data) => {
        const items = data.conflicts || [];
        confResultEl.innerHTML =
          `<div class="aisb-card aisb-summary-card">${ctx.escapeHtml(data.summary)}</div>` +
          (items
            .map(
              (c) => `<div class="aisb-card ${c.severity === "high" ? "aisb-risk-overdue" : "aisb-risk-due_soon"}">
                <span class="aisb-risk-tag">${conflictTypeLabel[c.type] || c.type}</span> ${ctx.escapeHtml(c.date)}<br>
                ${ctx.escapeHtml(c.message)}
              </div>`
            )
            .join("") || "");
      })
      .catch((err) => (confResultEl.innerHTML = `<p>エラー: ${err}</p>`))
      .finally(() => (btn.disabled = false));
  });
};
