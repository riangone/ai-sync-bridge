// Service Worker (Manifest V3)
// 役割: プロファイル設定の初期化・拡張全体の状態管理のみ。UI描画は content script が担当。

const DEFAULT_PROFILE = {
  profileId: "template",
  displayName: "Demo Legacy ERP",
  legacyOrigin: "http://localhost:5010",
  apiBaseUrl: "http://localhost:5011",
  sidebarWidthPx: 380,
  panels: [
    { id: "chat", label: "AIチャット", enabled: true },
    { id: "customers", label: "顧客検索", enabled: true },
    { id: "ocr", label: "OCR取込", enabled: true },
    { id: "search", label: "セマンティック検索", enabled: true },
  ],
};

chrome.runtime.onInstalled.addListener(async () => {
  const existing = await chrome.storage.local.get("activeProfile");
  if (!existing.activeProfile) {
    await chrome.storage.local.set({ activeProfile: DEFAULT_PROFILE, sidebarOpen: true });
  }
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
