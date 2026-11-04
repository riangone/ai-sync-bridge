// modules/panel-assistant.js — 画面認識型AIアシスタントパネル(README 4.3 panel-assistant.js相当)
// POST /api/local-ai/assist(message, screenContext, conversationId) → 会話形式のチャットUI
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.assistant = function renderAssistantPanel(el, ctx) {
  el.innerHTML = `
    <p class="aisb-hint">今開いている画面の情報を自動で渡しながら会話します(サーバー側に会話履歴は最新20往復まで保持)。</p>
    <div id="aisb-assist-log" style="height:calc(100vh - 260px);overflow-y:auto;margin-bottom:8px"></div>
    <div id="aisb-assist-actions" class="aisb-chip-row"></div>
    <div class="aisb-inline-row">
      <input id="aisb-assist-input" type="text" placeholder="質問や依頼を入力..." />
      <button id="aisb-assist-send">送信</button>
      <button id="aisb-assist-reset" title="会話をリセット">↺</button>
    </div>
  `;
  const log = el.querySelector("#aisb-assist-log");
  const actionsEl = el.querySelector("#aisb-assist-actions");
  const input = el.querySelector("#aisb-assist-input");

  // パネルのpaneはタブ切替後もDOMごと保持される(ui-base.js参照)ので、この関数内で
  // 宣言したclosure変数はタブを行き来しても維持される(ページリロードまでは有効)。
  let conversationId = crypto.randomUUID();

  function appendMsg(role, text) {
    const div = document.createElement("div");
    div.className = `aisb-msg aisb-msg-${role}`;
    div.textContent = text;
    log.appendChild(div);
    log.scrollTop = log.scrollHeight;
  }

  function buildScreenContext() {
    const detected = ctx.detectLegacyContext();
    return {
      screenType: detected ? `${detected.entity}/${detected.action}` : "dashboard",
      url: location.href,
      title: document.title,
    };
  }

  async function send(message) {
    if (!message) return;
    appendMsg("user", message);
    input.value = "";
    actionsEl.innerHTML = "";
    try {
      const data = await ctx.postJson(`${ctx.API_BASE}/api/local-ai/assist`, {
        message,
        screen_context: buildScreenContext(),
        conversation_id: conversationId,
      });
      conversationId = data.conversation_id;
      appendMsg("assistant", data.response);
      actionsEl.innerHTML = (data.suggested_actions || [])
        .map((a) => `<button class="aisb-chip">${ctx.escapeHtml(a)}</button>`)
        .join("");
      actionsEl.querySelectorAll(".aisb-chip").forEach((chip) => {
        chip.addEventListener("click", () => {
          input.value = chip.textContent;
          input.focus();
        });
      });
    } catch (e) {
      appendMsg("assistant", `[エラー] ${e}`);
    }
  }

  el.querySelector("#aisb-assist-send").addEventListener("click", () => send(input.value.trim()));
  input.addEventListener("keydown", (e) => e.key === "Enter" && send(input.value.trim()));
  el.querySelector("#aisb-assist-reset").addEventListener("click", () => {
    conversationId = crypto.randomUUID();
    log.innerHTML = "";
    actionsEl.innerHTML = "";
  });
};
