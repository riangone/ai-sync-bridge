// modules/panel-purchase.js — 発注管理パネル(README 4.3 panel-purchase.js相当)
// GET /api/purchase-order(一覧) / POST(作成) / GET propose(発注提案・ルールベース)
// / GET propose/insight(AI解釈・オプトイン) / GET supplier-evaluation / POST goods-receipt(入荷登録)
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.purchase = function renderPurchasePanel(el, ctx) {
  const statusLabel = { ordered: "発注済", received: "入荷済", cancelled: "取消" };
  el.innerHTML = `
    <div class="aisb-section-title">発注一覧</div>
    <div id="aisb-po-list">読込中...</div>
    <div class="aisb-inline-row">
      <input type="number" id="aisb-po-product-id" placeholder="商品ID" style="width:70px" />
      <input type="text" id="aisb-po-supplier" placeholder="仕入先" />
      <input type="number" id="aisb-po-qty" placeholder="数量" style="width:70px" />
      <input type="text" id="aisb-po-expected" placeholder="納期(YYYY-MM-DD)" />
      <button id="aisb-po-create">発注登録</button>
    </div>
    <div class="aisb-btn-row">
      <button id="aisb-po-propose-btn" class="aisb-btn-secondary">発注提案を生成</button>
      <button id="aisb-po-eval-btn" class="aisb-btn-secondary">仕入先評価を表示</button>
    </div>
    <div id="aisb-po-propose"></div>
    <div class="aisb-btn-row">
      <button id="aisb-po-insight-btn" class="aisb-btn-secondary">AIで発注提案を解釈する</button>
    </div>
    <div id="aisb-po-insight"></div>
    <div id="aisb-po-eval"></div>
  `;
  const listEl = el.querySelector("#aisb-po-list");
  const proposeEl = el.querySelector("#aisb-po-propose");
  const evalEl = el.querySelector("#aisb-po-eval");

  el.querySelector("#aisb-po-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/purchase-order/propose/insight`, e.target, el.querySelector("#aisb-po-insight"))
  );

  function loadList() {
    fetch(`${ctx.API_BASE}/api/purchase-order`)
      .then((r) => r.json())
      .then((pos) => {
        listEl.innerHTML =
          pos
            .map(
              (po) => `<div class="aisb-card" data-id="${po.id}">
            #${po.id} <b>${ctx.escapeHtml(po.supplier)}</b> / 商品ID:${po.product_id} / 数量:${po.qty}
            <span class="aisb-badge">${statusLabel[po.status] || po.status}</span><br>
            発注日:${po.ordered_at} 納期:${po.expected_date || "-"} 入荷済数量:${po.received_qty}
            ${
              po.status === "ordered"
                ? `<div class="aisb-btn-row"><button class="aisb-po-receive-btn aisb-btn-secondary">入荷登録</button></div>`
                : ""
            }
          </div>`
            )
            .join("") || "<p>発注データがありません</p>";

        listEl.querySelectorAll(".aisb-po-receive-btn").forEach((btn) => {
          btn.addEventListener("click", (ev) => {
            const id = ev.target.closest(".aisb-card").dataset.id;
            const qty = prompt("入荷数量を入力してください");
            if (qty === null || qty === "") return;
            ctx
              .postJson(`${ctx.API_BASE}/api/purchase-order/goods-receipt`, {
                purchase_order_id: Number(id),
                received_qty: Number(qty),
              })
              .then(loadList)
              .catch((e) => alert(`エラー: ${e}`));
          });
        });
      })
      .catch((e) => (listEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  el.querySelector("#aisb-po-create").addEventListener("click", () => {
    const productId = el.querySelector("#aisb-po-product-id").value;
    const supplier = el.querySelector("#aisb-po-supplier").value.trim();
    const qty = el.querySelector("#aisb-po-qty").value;
    const expected = el.querySelector("#aisb-po-expected").value.trim();
    if (!productId || !supplier || !qty) {
      alert("商品ID・仕入先・数量は必須です");
      return;
    }
    ctx
      .postJson(`${ctx.API_BASE}/api/purchase-order`, {
        product_id: Number(productId),
        supplier,
        qty: Number(qty),
        expected_date: expected || null,
      })
      .then(() => {
        el.querySelector("#aisb-po-product-id").value = "";
        el.querySelector("#aisb-po-supplier").value = "";
        el.querySelector("#aisb-po-qty").value = "";
        el.querySelector("#aisb-po-expected").value = "";
        loadList();
      })
      .catch((e) => alert(`エラー: ${e}`));
  });

  el.querySelector("#aisb-po-propose-btn").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    proposeEl.textContent = "生成中...";
    fetch(`${ctx.API_BASE}/api/purchase-order/propose`)
      .then((r) => r.json())
      .then((data) => {
        proposeEl.innerHTML =
          (data.proposals || [])
            .map(
              (p) => `<div class="aisb-card">
            <b>${ctx.escapeHtml(p.product_name)}</b>(現在庫:${p.current_stock} / 発注点:${p.reorder_point})<br>
            推奨発注数: <b>${p.suggested_qty}</b> / 仕入先: ${ctx.escapeHtml(p.supplier)}<br>
            ${ctx.escapeHtml(p.reason)}
          </div>`
            )
            .join("") || "<p>提案対象はありません</p>";
      })
      .catch((e) => (proposeEl.innerHTML = `<p>エラー: ${e}</p>`))
      .finally(() => (btn.disabled = false));
  });

  el.querySelector("#aisb-po-eval-btn").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    evalEl.textContent = "集計中...";
    const ratingClass = { good: "on_track", normal: "due_soon", caution: "overdue" };
    const ratingLabel = { good: "良好", normal: "普通", caution: "要注意" };
    fetch(`${ctx.API_BASE}/api/purchase-order/supplier-evaluation`)
      .then((r) => r.json())
      .then((data) => {
        evalEl.innerHTML =
          (data.evaluations || [])
            .map(
              (v) => `<div class="aisb-card aisb-risk-${ratingClass[v.rating] || "due_soon"}">
            <b>${ctx.escapeHtml(v.supplier)}</b><span class="aisb-risk-tag">${ratingLabel[v.rating] || v.rating}</span><br>
            発注件数:${v.order_count} / 累計数量:${v.total_qty} / 納期遵守率:${Math.round(v.on_time_rate * 100)}%
          </div>`
            )
            .join("") || "<p>評価対象はありません</p>";
      })
      .catch((e) => (evalEl.innerHTML = `<p>エラー: ${e}</p>`))
      .finally(() => (btn.disabled = false));
  });

  loadList();
};
