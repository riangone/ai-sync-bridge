// legacyOrigin (レガシー画面を開いているオリジン) から対応するAPIオリジンを引く表。
// 保存済みprofile.apiBaseUrlは拡張インストール時点の値で固定されており、
// 例えば「サーバー機上ではlocalhostで動作確認していたが、実際はユーザーは
// 公開ドメイン https://aisync.0101.click 経由で自分のPCから開いている」場合、
// localhost:5011はユーザー自身のPCを指してしまい接続不能になる。
// アクティブタブの実オリジンを見て、既知の組ならこちらを優先する。
const ORIGIN_API_MAP = {
  "http://localhost:5010": "http://localhost:5011",
  "https://aisync.0101.click": "https://aisync-api.0101.click",
};

async function resolveApiBase(fallback) {
  try {
    const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
    const tabOrigin = tab?.url ? new URL(tab.url).origin : null;
    if (tabOrigin && ORIGIN_API_MAP[tabOrigin]) {
      return ORIGIN_API_MAP[tabOrigin];
    }
  } catch (e) {
    // タブURL取得不可（権限不足等）。フォールバックを使う。
  }
  return fallback;
}

async function init() {
  const { activeProfile, sidebarOpen } = await chrome.storage.local.get([
    "activeProfile",
    "sidebarOpen",
  ]);
  const profile = activeProfile || {};
  const apiBase = await resolveApiBase(profile.apiBaseUrl || "http://localhost:5011");

  document.getElementById("profileName").textContent = profile.displayName || "template";
  document.getElementById("legacyOrigin").textContent = profile.legacyOrigin || "http://localhost:5010";
  document.getElementById("apiBase").textContent = apiBase;

  const toggle = document.getElementById("sidebarToggle");
  toggle.checked = sidebarOpen !== false;
  toggle.addEventListener("change", () => {
    chrome.runtime.sendMessage({ type: "TOGGLE_SIDEBAR", value: toggle.checked });
  });

  const dot = document.getElementById("status-dot");
  const text = document.getElementById("status-text");
  try {
    const res = await fetch(`${apiBase}/api/health`);
    const data = await res.json();
    dot.className = "dot dot-ok";
    text.textContent = `API接続OK (demo=${data.demo_mode}, ai=${data.ai_provider})`;
  } catch (e) {
    dot.className = "dot dot-error";
    text.textContent = "APIサーバーに接続できません";
  }
}
init();
