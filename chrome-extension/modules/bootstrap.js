// modules/bootstrap.js — 最後に読み込まれるエントリーポイント。
// shared/* が用意した構成要素(config-base/dom-base/api-base/ui-base)と
// modules/panel-*.js が window.AISB.panels に登録したレンダラー群を組み合わせて
// 実際にサイドバーを起動する。ここには個々のパネルの中身の知識は置かない。
(async function () {
  // 拡張機能が再読み込み/更新された後、そのタブがまだリロードされていない場合、
  // このcontent scriptインスタンスは古い(無効化された)拡張コンテキストに紐づいたまま残る。
  // その状態で chrome.runtime.getURL() 等を呼ぶと "chrome-extension://invalid/" を返し
  // net::ERR_FAILED が発生する。実害はない(サイドバー自体は表示される)が、コンソールに
  // エラーが出続けるため、コンテキスト無効化を検知したら静かに終了する。
  if (!chrome.runtime?.id) return;

  const loaded = await window.AISB.configBase.loadContext();
  if (!loaded) return;
  const { profile, sidebarOpen, API_BASE, LEGACY_ORIGIN } = loaded;

  const client = window.AISB.apiBase.createClient(API_BASE, LEGACY_ORIGIN, window.AISB.domBase.escapeHtml);

  async function persistWidth(px) {
    try {
      const { activeProfile: latest } = await chrome.storage.local.get("activeProfile");
      const merged = { ...(latest || profile), sidebarWidthPx: px };
      await chrome.storage.local.set({ activeProfile: merged });
    } catch (e) {
      // コンテキスト無効化等は無視(次回起動時に既定値へ戻るだけ)
    }
  }

  // 各パネル(modules/panel-*.js)へ渡す共有コンテキスト。
  // ctx.refreshUnreadBadge は ui-base.initShell() が構築後にセットする。
  const ctx = {
    API_BASE,
    LEGACY_ORIGIN,
    escapeHtml: window.AISB.domBase.escapeHtml,
    renderChart: window.AISB.domBase.renderChart,
    renderStatusDistributionChart: window.AISB.domBase.renderStatusDistributionChart,
    LEGACY_ENTITIES: window.AISB.configBase.LEGACY_ENTITIES,
    INSTANCE: window.AISB.configBase.INSTANCE,
    detectLegacyContext: () => window.AISB.domBase.detectLegacyContext(window.AISB.configBase.LEGACY_ENTITIES),
    runInsight: client.runInsight,
    postJson: client.postJson,
    persistWidth,
  };

  const shell = window.AISB.uiBase.initShell({
    profile,
    sidebarOpen,
    CSS: window.AISB.domBase.CSS,
    panels: window.AISB.panels,
    ctx,
  });

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "TOGGLE_SIDEBAR") {
      shell.root.classList.toggle("aisb-collapsed", !msg.value);
    }
  });
})();
