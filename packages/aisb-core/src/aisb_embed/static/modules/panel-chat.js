// modules/panel-chat.js — AIチャットパネル
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.chat = function renderChatPanel(el, ctx) {
  el.innerHTML = `
    <div id="aisb-chat-a2a-bar" style="display:none;padding:6px 8px;margin-bottom:6px;background:#eef4ff;border:1px solid #c7d9ff;border-radius:6px;font-size:12px;color:#1e3a8a;align-items:center;gap:6px;flex-wrap:wrap">
      <label style="display:inline-flex;align-items:center;gap:5px;cursor:pointer;font-weight:600">
        <input id="aisb-chat-a2a-toggle" type="checkbox" />
        <span>🔗 A2A 跨システム連携</span>
      </label>
      <span id="aisb-chat-a2a-peers" style="color:#475569;font-size:11px"></span>
    </div>
    <div id="aisb-chat-log"></div>
    <div id="aisb-chat-input-row">
      <input id="aisb-chat-input" type="text" maxlength="2000" placeholder="質問を入力..." />
      <button id="aisb-chat-send">送信</button>
    </div>
  `;
  const log = el.querySelector("#aisb-chat-log");
  const input = el.querySelector("#aisb-chat-input");
  const a2aBar = el.querySelector("#aisb-chat-a2a-bar");
  const a2aToggle = el.querySelector("#aisb-chat-a2a-toggle");
  const a2aPeersLabel = el.querySelector("#aisb-chat-a2a-peers");
  // 画面に出ている会話と同じ寿命。固定値にすると訪問者どうしの履歴が混ざる。
  const sessionId = crypto.randomUUID();

  // A2A 連携は公開デモ経路(/api/a2a/demo/*)をペルソナ指定で呼ぶ。ロールの入口がない導入先
  // (ペルソナ不明)では出さない。現在のロールで委譲できる Peer があるときだけトグルを表示する。
  const persona = window.AISB_DEMO_ROLE ? window.AISB_DEMO_ROLE.id : null;
  if (persona) {
    fetch(`${ctx.API_BASE}/api/a2a/demo/peers?persona=${encodeURIComponent(persona)}`)
      .then((r) => (r.ok ? r.json() : null))
      .then((d) => {
        const peers = d && d.enabled && Array.isArray(d.peers) ? d.peers.filter((p) => p.allowed) : [];
        if (peers.length > 0) {
          a2aBar.style.display = "flex";
          a2aPeersLabel.textContent = `接続先: ${peers.map((p) => p.name.toUpperCase()).join(", ")}(回答の回数を接続先の数だけ多く消費します)`;
        }
      })
      .catch(() => {});
  }

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
      if (persona && a2aToggle.checked) {
        // 1問ごとに独立(公開ペルソナは訪問者で共有されるため、サーバー側で会話を持ち越さない)
        const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/federated-ask`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ persona, question: message.slice(0, 500) }),
        });
        const data = await res.json().catch(() => ({}));
        if (!res.ok) {
          appendMsg("assistant", `[エラー] ${data.detail || res.status}`);
          return;
        }
        const loc = data.local || {};
        const parts = [`【${data.agent || "自システム"}】\n${loc.answer || "(回答なし)"}\n(権限で除外 ${loc.acl_filtered ?? 0} 件)`];
        (data.peers || []).forEach((p) => {
          if (p.status === "forbidden") return;
          const head = `【A2A連携: ${p.peer.toUpperCase()} Agent${p.status === "completed" ? "" : ` (${p.status})`}】`;
          const filtered = p.acl_filtered != null ? `\n(相手側で権限により除外 ${p.acl_filtered} 件)` : "";
          parts.push(`${head}\n${p.answer || p.error || "(応答なし)"}${filtered}`);
        });
        appendMsg("assistant", parts.join("\n\n"));
        return;
      }

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
