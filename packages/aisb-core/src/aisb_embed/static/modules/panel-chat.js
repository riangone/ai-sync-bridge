// modules/panel-chat.js — AIチャットパネル
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.chat = function renderChatPanel(el, ctx) {
  el.innerHTML = `
    <div id="aisb-chat-log"></div>
    <div id="aisb-chat-input-row">
      <input id="aisb-chat-input" type="text" maxlength="2000" placeholder="質問を入力..." />
      <button id="aisb-chat-send">送信</button>
    </div>
  `;
  const log = el.querySelector("#aisb-chat-log");
  const input = el.querySelector("#aisb-chat-input");
  // 画面に出ている会話と同じ寿命。固定値にすると訪問者どうしの履歴が混ざる。
  const sessionId = crypto.randomUUID();

  function appendMsg(role, text) {
    const div = document.createElement("div");
    div.className = `aisb-msg aisb-msg-${role}`;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  async function send() {
    const message = input.value.trim();
    if (!message) return;
    appendMsg("user", message);
    input.value = "";
    try {
      const res = await fetch(`${ctx.API_BASE}/api/chat`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, message }),
      });
      const data = await res.json();
      appendMsg("assistant", res.ok ? data.reply : `[エラー] ${data.message || data.detail || res.status}`);
    } catch (e) {
      appendMsg("assistant", `[エラー] API接続に失敗しました: ${e}`);
    }
  }
  el.querySelector("#aisb-chat-send").addEventListener("click", send);
  input.addEventListener("keydown", (e) => e.key === "Enter" && send());
};
