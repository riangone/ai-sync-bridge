// modules/panel-legacy.js — 業務データパネル(自動車ディーラー全13エンティティ)
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.legacy = function renderLegacyDataPanel(el, ctx) {
  const { escapeHtml, LEGACY_ENTITIES, LEGACY_ORIGIN, API_BASE } = ctx;
  const ctxInfo = ctx.detectLegacyContext();

  el.innerHTML = `
    <div class="aisb-section-title">業務データ（自動車ディーラー 全13エンティティ）</div>
    <div id="aisb-legacy-context"></div>
    <div class="aisb-inline-row">
      <select id="aisb-legacy-entity">
        ${LEGACY_ENTITIES.map((e) => `<option value="${e.id}">${e.label}</option>`).join("")}
      </select>
    </div>
    <div class="aisb-inline-row">
      <input id="aisb-legacy-q" type="text" placeholder="キーワードで絞り込み..." />
      <button id="aisb-legacy-search-run">検索</button>
    </div>
    <div id="aisb-legacy-list">読込中...</div>
  `;

  const selectEl = el.querySelector("#aisb-legacy-entity");
  const qEl = el.querySelector("#aisb-legacy-q");
  const listEl = el.querySelector("#aisb-legacy-list");
  const contextEl = el.querySelector("#aisb-legacy-context");

  function currentMeta() {
    return LEGACY_ENTITIES.find((e) => e.id === selectEl.value) || LEGACY_ENTITIES[0];
  }

  function loadList() {
    const meta = currentMeta();
    const q = qEl.value.trim();
    listEl.textContent = "読込中...";
    const url = new URL(`${LEGACY_ORIGIN}/api/${meta.id}/list`);
    if (q) url.searchParams.set("q", q);
    fetch(url)
      .then((r) => r.json())
      .then((data) => {
        const rows = data.rows || [];
        if (!rows.length) {
          listEl.innerHTML = "<p>該当データがありません</p>";
          return;
        }
        listEl.innerHTML = `
          <div class="aisb-badge">${data.count}件${q ? `（"${escapeHtml(q)}"で絞込）` : ""}</div>
          <table class="aisb-table">
            <thead><tr>${meta.cols.map((c) => `<th>${c}</th>`).join("")}${meta.hasDetail ? "<th></th>" : ""}</tr></thead>
            <tbody>
              ${rows
                .map(
                  (row) => `<tr>
                    ${meta.cols.map((c) => `<td>${escapeHtml(row[c])}</td>`).join("")}
                    ${meta.hasDetail && row.Id ? `<td><a class="aisb-link-btn" href="${LEGACY_ORIGIN}/${meta.id}/Detail/${encodeURIComponent(row.Id)}" target="_blank" rel="noopener">開く</a></td>` : meta.hasDetail ? "<td></td>" : ""}
                  </tr>`
                )
                .join("")}
            </tbody>
          </table>
        `;
      })
      .catch((e) => (listEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  // AIチャットAPIへレコードのJSONを渡して要約させる。他パネル(chat)のセッションとは
  // 独立させ、同じ画面で何度呼んでも会話が肥大化しないよう毎回新規セッションにする。
  async function summarizeRecord(meta, record, items, btn, outEl) {
    btn.disabled = true;
    btn.textContent = "AI要約中...";
    outEl.innerHTML = "";
    const payload = { ...record };
    if (items && items.length) payload._items = items;
    const message =
      `以下は基幹システムの「${meta.label}」レコード(JSON)です。業務担当者向けに、` +
      `要点・注意すべき点(与信/納期/在庫/滞留等があれば)を日本語で3行程度で要約してください。\n` +
      JSON.stringify(payload);
    try {
      const res = await fetch(`${API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: `legacy-ctx-${meta.id}-${record.Id || Date.now()}`, message }),
      });
      const data = await res.json();
      outEl.innerHTML = `<div class="aisb-card">${escapeHtml(data.reply)}</div>`;
    } catch (e) {
      outEl.innerHTML = `<p>エラー: ${e}</p>`;
    } finally {
      btn.disabled = false;
      btn.textContent = "AIで要約する";
    }
  }

  function renderContextBanner() {
    if (!ctxInfo) {
      contextEl.innerHTML = "";
      return;
    }
    const meta = LEGACY_ENTITIES.find((e) => e.id === ctxInfo.entity);
    const actionLabel = { List: "一覧", Entry: "登録/編集", Detail: "詳細", Search: "検索", Inquiry: "照会", Register: "登録" }[ctxInfo.action] || ctxInfo.action;
    contextEl.innerHTML = `
      <div class="aisb-context-banner">
        現在の画面: <b>${meta.label}${actionLabel}</b>${ctxInfo.id ? `（ID: ${escapeHtml(ctxInfo.id)}）` : ""}
        ${meta.hasDetail && ctxInfo.action === "Detail" && ctxInfo.id ? `<br><button class="aisb-summarize-btn">AIで要約する</button><div id="aisb-legacy-summary"></div>` : ""}
      </div>
    `;
    const summarizeBtn = contextEl.querySelector(".aisb-summarize-btn");
    if (summarizeBtn) {
      summarizeBtn.addEventListener("click", async () => {
        const outEl = contextEl.querySelector("#aisb-legacy-summary");
        try {
          const res = await fetch(`${LEGACY_ORIGIN}/api/${ctxInfo.entity}/detail/${encodeURIComponent(ctxInfo.id)}`);
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          const data = await res.json();
          await summarizeRecord(meta, data.record, data.items, summarizeBtn, outEl);
        } catch (e) {
          outEl.innerHTML = `<p>エラー: ${e}</p>`;
        }
      });
    }
  }

  if (ctxInfo) selectEl.value = ctxInfo.entity;
  renderContextBanner();
  selectEl.addEventListener("change", loadList);
  el.querySelector("#aisb-legacy-search-run").addEventListener("click", loadList);
  qEl.addEventListener("keydown", (e) => e.key === "Enter" && loadList());
  loadList();
};
