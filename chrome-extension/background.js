// Service Worker (Manifest V3)
// 役割: プロファイル設定の初期化・拡張全体の状態管理のみ。UI描画は content script が担当。

const DEFAULT_PROFILE = {
  profileId: "template",
  displayName: "Demo Legacy ERP",
  legacyOrigin: "http://localhost:5010",
  apiBaseUrl: "http://localhost:5011",
  sidebarWidthPx: 380,
  // AI関連機能に絞って表示する暫定措置。shared/config-base.js のコメント参照。
  panels: [
    { id: "chat", label: "AIチャット", enabled: true },
    { id: "legacy", label: "業務データ", enabled: false },
    { id: "nlsql", label: "AI検索", enabled: true },
    { id: "customers", label: "顧客検索", enabled: false },
    { id: "ocr", label: "OCR取込", enabled: true },
    { id: "search", label: "セマンティック検索", enabled: true },
    { id: "analytics", label: "予測分析", enabled: true },
    { id: "workflows", label: "ワークフロー", enabled: false },
    { id: "notifications", label: "通知", enabled: false },
    { id: "admin", label: "管理", enabled: false },
  ],
};

chrome.runtime.onInstalled.addListener(async (details) => {
  const existing = await chrome.storage.local.get("activeProfile");
  if (!existing.activeProfile) {
    await chrome.storage.local.set({ activeProfile: DEFAULT_PROFILE, sidebarOpen: true });
    return;
  }
  // 拡張の更新(reason === "update")では、既存プロファイルのユーザー操作由来の状態
  // (表示名/sidebarWidthPx等)は保持する。panels(どのパネルを表示するか)はユーザーが
  // カスタマイズするUIが存在しないコード管理の設定なので、ここでマージする必要はない
  // — shared/config-base.js の loadContext() が読み込み時に常にDEFAULT_PROFILE.panels
  // で上書きする(新パネルの追加や有効/無効の変更を、古いストレージの内容に関わらず
  // 即座に反映するため)。
});

// popup からのメッセージ (サイドバー表示切替) を content script へ中継
chrome.runtime.onMessage.addListener((msg, _sender, sendResponse) => {
  if (msg.type === "TOGGLE_SIDEBAR") {
    chrome.storage.local.set({ sidebarOpen: msg.value });
    chrome.tabs.query({ active: true, currentWindow: true }, (tabs) => {
      if (tabs[0]?.id) {
        chrome.tabs.sendMessage(tabs[0].id, { type: "TOGGLE_SIDEBAR", value: msg.value });
      }
    });
    sendResponse({ ok: true });
  }
  return true;
});
