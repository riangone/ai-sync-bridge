// modules/panel-bridge.js — 権限付き検索・差分同期・監査ログ(/api/bridge のデモUI)
//
// 見せたいこと(業種非依存):
//   1. 同じ質問でも、呼び出し主体(テナント/ロール/部署)ごとに返る文書が違う(ACL)
//   2. 差分同期: 2回目以降は変更分だけを再ベクトル化する(unchanged が大半になる)
//   3. 全検索・全同期がハッシュチェーン付き監査ログに残り、改ざん検証できる
//   4. AI回答(RAG)も同じ権限の範囲内でしか答えない(/api/bridge/ask)。根拠文書と監査IDを表示
//
// 主体の切り替えはサーバー側で行う(/api/bridge/demo/*)。ブラウザに API キーは置かない。
// 主体の一覧は導入先 bridge.yaml の demo.personas から取得する。
// ロールを選んで入る導入先(window.AISB_DEMO_ROLE あり)では、現在のロールでの検索を主操作にし、
// 全主体の比較は別ボタンとして残す。ロールなしの導入先では従来どおり比較だけを出す。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.bridge = function renderBridgePanel(el, ctx) {
  const esc = ctx.escapeHtml;
  const SAMPLE_QUERIES = window.AISB.configBase.BRIDGE_SAMPLE_QUERIES || ["経理部の従業員を教えて", "経理部 課長", "営業部 出荷", "未払い 請求"];
  const ME = window.AISB_DEMO_ROLE || null;
  const AUDIT_NOTE = "すべての検索は監査ログに記録されます(公開デモのため、入力内容そのものは保存しません)。";

  el.innerHTML = `
    <div class="aisb-bridge-intro" style="font-size:12px;color:#555;line-height:1.6;margin-bottom:8px">
      ${ME
        ? `<b>${esc(ME.label)}</b>(${esc(ME.note)})の権限で検索・AI回答します。業務画面と同じ権限が適用され、${AUDIT_NOTE}`
        : `同じ質問を<b>権限の異なる利用者</b>で同時に検索・AI回答させます。レガシー側の権限(テナント/ロール/部署)が検索結果にそのまま反映され、${AUDIT_NOTE}`}
    </div>
    <div id="aisb-search-row">
      <input id="aisb-bridge-q" type="text" value="${esc(SAMPLE_QUERIES[0] || "")}" placeholder="例: 経理部 課長" />
      ${ME
        ? `<button id="aisb-bridge-self-run">検索</button>
           <button id="aisb-bridge-self-ask" title="現在のロールの権限でAIに回答させる">AI回答</button>`
        : ""}
      ${ME ? "" : `<button id="aisb-bridge-run">比較検索</button>
      <button id="aisb-bridge-ask" title="同じ質問を各利用者の権限でAIに回答させる">AI回答を比較</button>`}
    </div>
    ${ME
      ? `<div style="font-size:11px;color:#666;margin:4px 0">
           権限比較:
           <button id="aisb-bridge-run">比較検索</button>
           <button id="aisb-bridge-ask" title="同じ質問を各利用者の権限でAIに回答させる">AI回答を比較</button>
           (AI回答の比較は利用者の人数分の回数を消費します)
         </div>`
      : ""}
    <div style="margin:4px 0 6px">${SAMPLE_QUERIES.map((q) => `<button class="aisb-bridge-chip" data-q="${esc(q)}" style="font-size:11px;padding:2px 8px;margin:0 4px 4px 0">${esc(q)}</button>`).join("")}</div>
    <div id="aisb-bridge-results"></div>
    <div style="display:flex;gap:6px;flex-wrap:wrap;margin-top:10px">
      <button id="aisb-bridge-sync">差分同期を実行</button>
      <button id="aisb-bridge-audit">監査ログ</button>
      <button id="aisb-bridge-verify">改ざん検証</button>
    </div>
    <div id="aisb-bridge-ops" style="margin-top:8px"></div>
  `;
  const $ = (s) => el.querySelector(s);

  async function call(method, path, body) {
    const res = await fetch(`${ctx.API_BASE}/api/bridge/demo${path}`, {
      method,
      headers: { "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(`${res.status} ${data.detail || ""}`.trim());
    return data;
  }

  const personasReady = call("GET", "/personas").then((d) => d.personas);
  const selfOnly = (all) => all.filter((p) => p.id === ME.id);

  function refLabel(r) {
    return `<span class="aisb-badge">${esc(r.entity)}</span> ${esc(r.title || r.pk)}`;
  }

  // 比較検索とAI回答比較は同じ結果欄を使うため、共通の世代番号で「後から始めた方」だけを描画する
  let resultsSeq = 0;

  async function compare(pick) {
    const q = $("#aisb-bridge-q").value.trim();
    const out = $("#aisb-bridge-results");
    if (!q) return;
    const seq = ++resultsSeq;
    out.textContent = "検索中...";
    let PRINCIPALS;
    try {
      PRINCIPALS = await personasReady;
    } catch (e) {
      out.textContent = `エラー: ${e.message}`;
      return;
    }
    if (pick) PRINCIPALS = pick(PRINCIPALS);
    const settled = await Promise.allSettled(PRINCIPALS.map((p) => call("POST", "/search", { persona: p.id, query: q })));
    if (seq !== resultsSeq) return;
    out.innerHTML = settled
      .map((s, i) => {
        const p = PRINCIPALS[i];
        const head = `<b>${esc(p.label)}</b> <span style="color:#888">(${esc(p.note)})</span>`;
        if (s.status === "rejected") return `<div class="aisb-card">${head}<br><span style="color:#d03b3b">${esc(String(s.reason.message || s.reason))}</span></div>`;
        const d = s.value;
        const items = d.results.length
          ? d.results.map((r) => `<li>${refLabel(r)}</li>`).join("")
          : `<li style="color:#888">閲覧できる範囲に該当なし</li>`;
        return `<div class="aisb-card">${head}
          <div style="font-size:11px;color:#666">表示 ${d.results.length} 件 / 権限で除外 ${d.acl_filtered} 件 · ${esc(d.strategy)} · 監査ID ${esc(String(d.audit_id).slice(0, 8))}</div>
          <ul style="margin:4px 0 0 16px;padding:0">${items}</ul></div>`;
      })
      .join("");
  }

  // AI回答の比較: LLM 呼び出しは数秒〜数十秒かかるため、返ってきた主体から順に描画する
  async function askCompare(pick) {
    const q = $("#aisb-bridge-q").value.trim();
    const out = $("#aisb-bridge-results");
    if (!q) return;
    const seq = ++resultsSeq;
    let PRINCIPALS;
    try {
      PRINCIPALS = await personasReady;
    } catch (e) {
      out.textContent = `エラー: ${e.message}`;
      return;
    }
    if (seq !== resultsSeq) return;
    if (pick) PRINCIPALS = pick(PRINCIPALS);
    out.innerHTML = PRINCIPALS.map(
      (p, i) => `<div class="aisb-card" id="aisb-ask-${i}"><b>${esc(p.label)}</b> <span style="color:#888">(${esc(p.note)})</span>
        <div style="color:#888;font-size:12px">AIが回答を作成中...</div></div>`,
    ).join("");
    PRINCIPALS.forEach(async (p, i) => {
      let html;
      try {
        const d = await call("POST", "/ask", { persona: p.id, question: q });
        const cites = d.citations.length
          ? d.citations.map((c) => `<li>[${c.n}] ${refLabel(c)}</li>`).join("")
          : `<li style="color:#888">${d.llm_called ? "根拠文書の引用なし" : "閲覧できる範囲に関係する文書がないため AI は呼び出していません"}</li>`;
        html = `<div style="white-space:pre-wrap;font-size:12px;margin:4px 0">${esc(d.answer)}</div>
          <div style="font-size:11px;color:#666">根拠(閲覧可能な文書のみ): 渡した ${d.context_count} 件 / 権限で除外 ${d.acl_filtered} 件 · 監査ID ${esc(String(d.audit_id).slice(0, 8))}</div>
          <ul style="margin:2px 0 0 16px;padding:0;font-size:11px">${cites}</ul>`;
      } catch (e) {
        html = `<span style="color:#d03b3b">${esc(e.message)}</span>`;
      }
      if (seq !== resultsSeq) return; // 新しい比較が始まっていれば古い結果は捨てる
      const card = $(`#aisb-ask-${i}`);
      if (card) card.innerHTML = `<b>${esc(p.label)}</b> <span style="color:#888">(${esc(p.note)})</span>${html}`;
    });
  }

  async function sync() {
    const out = $("#aisb-bridge-ops");
    out.textContent = "同期中...";
    try {
      const d = await call("POST", "/sync");
      const rows = d.entities
        .map((e) => `<tr><td>${esc(e.source)}</td><td>${esc(e.entity)}</td><td>${e.source_unchanged ? '<span title="ファイル/ソースのハッシュが前回と同一のため読み込み自体を省略">未変更</span>' : e.fetched}</td><td><b>${e.upserted}</b></td><td>${e.unchanged}</td><td>${e.deleted}</td><td style="color:#d03b3b">${e.failed ? "失敗" : ""}</td></tr>`)
        .join("");
      out.innerHTML = `<div class="aisb-card">
        <b>差分同期</b> ${d.cached ? "(直前の結果を表示)" : `${d.elapsed_ms}ms`} — 再ベクトル化 ${d.upserted} 件 / 変更なし ${d.unchanged} 件 / 削除 ${d.deleted} 件
        <table style="width:100%;font-size:11px;margin-top:4px;border-collapse:collapse">
          <tr style="color:#666"><th align=left>接続元</th><th align=left>対象</th><th>取得</th><th>更新</th><th>不変</th><th>削除</th><th></th></tr>${rows}
        </table></div>`;
    } catch (e) {
      out.textContent = `エラー: ${e.message}`;
    }
  }

  function auditSummary(it) {
    const c = it.counts || {};
    if (it.kind === "retrieval") return `検索 → ${c.returned} 件返却 / ${c.acl_filtered} 件除外`;
    if (it.kind === "rag.answer") return `AI回答 → 根拠 ${c.context} 件 / 引用 ${c.cited} 件${c.llm_called ? "" : "(AI未呼出)"}`;
    if (it.kind === "sync.run") return `更新 ${c.upserted} / 不変 ${c.unchanged} / 削除 ${c.deleted}`;
    return esc([it.source, it.entity, it.ref].filter(Boolean).join("/"));
  }

  async function audit() {
    const out = $("#aisb-bridge-ops");
    out.textContent = "読み込み中...";
    try {
      const d = await call("GET", "/audit");
      out.innerHTML = `<div class="aisb-card"><b>監査ログ(新しい順)</b>${d.items
        .map((it) => `<div style="font-size:11px;border-top:1px solid #eee;padding:3px 0">
            #${it.seq} ${new Date(it.ts * 1000).toLocaleTimeString("ja-JP")} <span class="aisb-badge">${esc(it.kind)}</span>
            ${esc(it.actor || "")} — ${auditSummary(it)}
            <span style="color:#aaa;font-family:monospace">${esc(it.hash.slice(0, 10))}</span></div>`)
        .join("")}</div>`;
    } catch (e) {
      out.textContent = `エラー: ${e.message}`;
    }
  }

  async function verify() {
    const out = $("#aisb-bridge-ops");
    try {
      const d = await call("GET", "/audit/verify");
      out.innerHTML = d.ok
        ? `<div class="aisb-card" style="color:#0ca30c">✔ ハッシュチェーン整合: ${d.checked} 件を検証(先頭 ${esc(String(d.head).slice(0, 10))})</div>`
        : `<div class="aisb-card" style="color:#d03b3b">✘ 改ざん/欠落を検出: ${esc(JSON.stringify(d))}</div>`;
    } catch (e) {
      out.textContent = `エラー: ${e.message}`;
    }
  }

  const primarySearch = () => compare(ME ? selfOnly : null);
  $("#aisb-bridge-run").addEventListener("click", () => compare());
  $("#aisb-bridge-ask").addEventListener("click", () => askCompare());
  if (ME) {
    $("#aisb-bridge-self-run").addEventListener("click", primarySearch);
    $("#aisb-bridge-self-ask").addEventListener("click", () => askCompare(selfOnly));
  }
  el.querySelectorAll(".aisb-bridge-chip").forEach((b) =>
    b.addEventListener("click", () => {
      $("#aisb-bridge-q").value = b.dataset.q;
      primarySearch();
    }),
  );
  $("#aisb-bridge-q").addEventListener("keydown", (e) => e.key === "Enter" && primarySearch());
  $("#aisb-bridge-sync").addEventListener("click", sync);
  $("#aisb-bridge-audit").addEventListener("click", audit);
  $("#aisb-bridge-verify").addEventListener("click", verify);
};
