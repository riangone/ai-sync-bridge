// shared/dom-base.js — 埋め込み版
// chrome-extension/shared/dom-base.js の移植版。CSSは(chrome-extension版のような
// getURL/fetchのレース問題が同一オリジン配信では起きないため)インライン複製せず、
// 通常の <link rel="stylesheet" href="/aisb-embed/static/sidebar.css"> で読み込む
// (ui-base.js 側で付与)。ここには escapeHtml と detectLegacyContext のみを置く。
window.AISB = window.AISB || {};

window.AISB.domBase = (function () {
  function escapeHtml(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // 今開いているレガシー画面のURLからエンティティ・画面種別・IDを読み取る。
  // legacyEntities は shared/config-base.js の LEGACY_ENTITIES を呼び出し側から渡す。
  function detectLegacyContext(legacyEntities) {
    const m = location.pathname.match(/^\/([A-Za-z]+)\/(List|Entry|Detail|Search|Inquiry|Register)(?:\/([^/]+))?/);
    if (!m) return null;
    const [, entity, action, id] = m;
    if (!legacyEntities.some((e) => e.id === entity)) return null;
    return { entity, action, id: id || null };
  }

  // クロス分析(与信リスク/在庫逼迫/滞留債権)向けの「ランキング型横棒チャート」。
  // chrome-extension/shared/dom-base.js と同一内容(移植版のため)。
  function renderRankedBarChart(chart) {
    const categories = chart?.categories || [];
    if (!categories.length) return "<p>該当データがありません</p>";
    const unit = chart.unit || "";

    if (chart.type === "ranked-bar-grouped" && (chart.series || []).length >= 2) {
      const limits = chart.series[0].values;
      const actuals = chart.series[1].values;
      const legend =
        `<div class="aisb-legend">` +
        `<span><span class="aisb-legend-dot" style="background:#c7d8ec"></span>${escapeHtml(chart.series[0].label)}</span>` +
        `<span><span class="aisb-legend-dot" style="background:#3a6ea5"></span>${escapeHtml(chart.series[1].label)}</span>` +
        `</div>`;
      const rows = categories
        .map((cat, i) => {
          const limit = Number(limits[i]) || 0;
          const actual = Number(actuals[i]) || 0;
          const ratio = limit > 0 ? actual / limit : 0;
          const pct = Math.max(2, Math.min(100, Math.round(ratio * 100)));
          const stateClass = ratio >= 1 ? "aisb-hbar-over" : ratio >= 0.8 ? "aisb-hbar-warn" : "";
          return `<div class="aisb-hbar-row">
            <div class="aisb-hbar-label" title="${escapeHtml(cat)}">${escapeHtml(cat)}</div>
            <div class="aisb-hbar-track ${stateClass}"><div class="aisb-hbar-fill" style="width:${pct}%"></div></div>
            <div class="aisb-hbar-value">${Math.round(actual).toLocaleString()} / ${Math.round(limit).toLocaleString()}${unit}</div>
          </div>`;
        })
        .join("");
      return legend + rows;
    }

    const values = (chart.series && chart.series[0] && chart.series[0].values) || [];
    const max = Math.max(...values.map((v) => Math.abs(Number(v) || 0)), 1);
    return categories
      .map((cat, i) => {
        const v = values[i];
        const pct = v == null ? 0 : Math.max(2, Math.min(100, Math.round((Math.abs(Number(v)) / max) * 100)));
        const display = v == null ? "-" : `${Math.round(Number(v)).toLocaleString()}${unit}`;
        return `<div class="aisb-hbar-row">
          <div class="aisb-hbar-label" title="${escapeHtml(cat)}">${escapeHtml(cat)}</div>
          <div class="aisb-hbar-track"><div class="aisb-hbar-fill" style="width:${pct}%"></div></div>
          <div class="aisb-hbar-value">${display}</div>
        </div>`;
      })
      .join("");
  }

  return { escapeHtml, detectLegacyContext, renderRankedBarChart };
})();
