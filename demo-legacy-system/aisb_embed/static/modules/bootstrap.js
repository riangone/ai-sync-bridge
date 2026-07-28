// modules/bootstrap.js — 埋め込み版エントリーポイント
// chrome-extension/modules/bootstrap.js の移植版。差分:
//   - chrome.runtime?.id ガード(拡張コンテキスト無効化検知)は該当コンテキストが
//     存在しないため無い
//   - chrome.runtime.onMessage (popupからの開閉指示の中継)は該当popupが存在しない
//     ため無い
//   - persistWidthはlocalStorageへの同期書き込み(configBase.saveJSON)
//
// この機能自体のON/OFFは aisb_embed/middleware.py が担当する(無効時はこの
// ファイル自体が読み込まれない)。読み込まれた時点で常に描画してよい。
(async function () {
  const loaded = await window.AISB.configBase.loadContext();
  const { profile, sidebarOpen, API_BASE, LEGACY_ORIGIN } = loaded;

  const client = window.AISB.apiBase.createClient(API_BASE, LEGACY_ORIGIN, window.AISB.domBase.escapeHtml);

  function persistWidth(px) {
    const latest = window.AISB.configBase.loadJSON(window.AISB.configBase.STORAGE_KEY_PROFILE, profile);
    const merged = { ...latest, sidebarWidthPx: px };
    window.AISB.configBase.saveJSON(window.AISB.configBase.STORAGE_KEY_PROFILE, merged);
  }

  const ctx = {
    API_BASE,
    LEGACY_ORIGIN,
    escapeHtml: window.AISB.domBase.escapeHtml,
    renderChart: window.AISB.domBase.renderChart,
    renderStatusDistributionChart: window.AISB.domBase.renderStatusDistributionChart,
    LEGACY_ENTITIES: window.AISB.configBase.LEGACY_ENTITIES,
    detectLegacyContext: () => window.AISB.domBase.detectLegacyContext(window.AISB.configBase.LEGACY_ENTITIES),
    runInsight: client.runInsight,
    postJson: client.postJson,
    persistWidth,
  };

  window.AISB.uiBase.initShell({
    profile,
    sidebarOpen,
    panels: window.AISB.panels,
    ctx,
  });
})();
