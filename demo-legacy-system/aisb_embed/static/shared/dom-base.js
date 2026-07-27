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

  return { escapeHtml, detectLegacyContext };
})();
