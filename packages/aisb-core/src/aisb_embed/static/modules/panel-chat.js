// modules/panel-chat.js — AIチャットパネル
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.chat = function renderChatPanel(el, ctx) {
  el.innerHTML = `
    <div id="aisb-chat-log"></div>
    <div id="aisb-chat-input-row">
      <input id="aisb-chat-input" type="text" placeholder="質問を入力..." />
      <button id="aisb-chat-send">送信</button>
    </div>
  `;
  const log = el.querySelector("#aisb-chat-log");
  const input = el.querySelector("#aisb-chat-input");

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
        body: JSON.stringify({ session_id: "sidebar", message }),
      });
      const data = await res.json();
      appendMsg("assistant", data.reply);
    } catch (e) {
      appendMsg("assistant", `[エラー] API接続に失敗しました: ${e}`);
    }
  }
  el.querySelector("#aisb-chat-send").addEventListener("click", send);
  input.addEventListener("keydown", (e) => e.key === "Enter" && send());
};
