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

  // クロス分析(与信リスク/在庫逼迫/滞留債権)・AIレポート自動生成 向けのチャート描画。
  // chrome-extension/shared/dom-base.js と同一内容(移植版のため)。renderChart()が
  // type(trend-line/ranked-bar-grouped/ranked-bar)ごとに描画関数へ振り分ける。
  function renderChart(chart) {
    if (chart && chart.type === "trend-line") return renderTrendLineChart(chart);
    return renderRankedBarChart(chart);
  }

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

  // 時系列トレンド(折れ線)。純SVGで描画。chrome-extension/shared/dom-base.js と同一内容。
  function renderTrendLineChart(chart) {
    const categories = chart?.categories || [];
    const values = (chart.series && chart.series[0] && chart.series[0].values) || [];
    if (!categories.length || !values.length) return "<p>該当データがありません</p>";
    const unit = chart.unit || "";
    const W = 280, H = 90, PAD_L = 4, PAD_R = 4, PAD_T = 12, PAD_B = 4;
    const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
    const nums = values.map((v) => Number(v) || 0);
    const max = Math.max(...nums, 0);
    const min = Math.min(...nums, 0);
    const range = max - min || 1;
    const stepX = categories.length > 1 ? plotW / (categories.length - 1) : 0;
    const pts = nums.map((v, i) => [
      PAD_L + stepX * i,
      PAD_T + plotH - ((v - min) / range) * plotH,
    ]);
    const zeroY = PAD_T + plotH - ((0 - min) / range) * plotH;
    const linePath = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const last = pts[pts.length - 1];
    const areaPath = `${linePath} L${last[0].toFixed(1)},${zeroY.toFixed(1)} L${pts[0][0].toFixed(1)},${zeroY.toFixed(1)} Z`;
    const dots = pts
      .map(([x, y], i) => {
        const r = i === pts.length - 1 ? 4 : 2.5;
        return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" class="aisb-trend-dot"/>`;
      })
      .join("");
    const lastLabel = `${Math.round(nums[nums.length - 1]).toLocaleString()}${unit}`;
    const labelAnchor = last[0] > W - 40 ? "end" : "middle";
    return `
      <svg viewBox="0 0 ${W} ${H}" class="aisb-trend-svg" preserveAspectRatio="none">
        <line x1="${PAD_L}" y1="${zeroY.toFixed(1)}" x2="${W - PAD_R}" y2="${zeroY.toFixed(1)}" class="aisb-trend-axis"/>
        <path d="${areaPath}" class="aisb-trend-area"></path>
        <path d="${linePath}" class="aisb-trend-line"></path>
        ${dots}
        <text x="${last[0].toFixed(1)}" y="${Math.max(10, last[1] - 8).toFixed(1)}" text-anchor="${labelAnchor}" class="aisb-trend-endlabel">${escapeHtml(lastLabel)}</text>
      </svg>
      <div class="aisb-trend-xlabels"><span>${escapeHtml(categories[0])}</span><span>${escapeHtml(categories[categories.length - 1])}</span></div>
    `;
  }

  // 状態分類の構成比(part-to-whole)。chrome-extension/shared/dom-base.js と同一内容。
  const STATUS_COLOR = { good: "#2e8b57", warning: "#d68910", critical: "#c0392b" };
  function renderStatusDistributionChart(distribution) {
    const slices = (distribution && distribution.slices) || [];
    const total = slices.reduce((s, x) => s + (Number(x.count) || 0), 0);
    if (!total) return "";
    const bar = slices
      .filter((s) => s.count > 0)
      .map((s) => {
        const pct = (s.count / total) * 100;
        const color = STATUS_COLOR[s.status] || "#8a94a6";
        return `<div class="aisb-dist-seg" style="width:${pct.toFixed(2)}%;background:${color}" title="${escapeHtml(s.label)}: ${s.count}件(${Math.round(pct)}%)"></div>`;
      })
      .join("");
    const legend = slices
      .map((s) => {
        const color = STATUS_COLOR[s.status] || "#8a94a6";
        const pct = Math.round((s.count / total) * 100);
        return `<span class="aisb-dist-legend-item"><span class="aisb-legend-dot" style="background:${color}"></span>${escapeHtml(s.label)} ${s.count}件(${pct}%)</span>`;
      })
      .join("");
    return `
      <div class="aisb-section-title">${escapeHtml(distribution.title || "内訳")}</div>
      <div class="aisb-dist-bar">${bar}</div>
      <div class="aisb-dist-legend">${legend}</div>
    `;
  }

  return { escapeHtml, detectLegacyContext, renderChart, renderStatusDistributionChart };
})();
