async function init() {
  const { activeProfile, sidebarOpen } = await chrome.storage.local.get([
    "activeProfile",
    "sidebarOpen",
  ]);
  const profile = activeProfile || {};
  document.getElementById("profileName").textContent = profile.displayName || "template";
  document.getElementById("legacyOrigin").textContent = profile.legacyOrigin || "http://localhost:5010";
  document.getElementById("apiBase").textContent = profile.apiBaseUrl || "http://localhost:5011";

  const toggle = document.getElementById("sidebarToggle");
  toggle.checked = sidebarOpen !== false;
  toggle.addEventListener("change", () => {
    chrome.runtime.sendMessage({ type: "TOGGLE_SIDEBAR", value: toggle.checked });
  });

  const apiBase = profile.apiBaseUrl || "http://localhost:5011";
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
