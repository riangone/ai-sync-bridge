// modules/panel-notifications.js — 通知パネル
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.notifications = function renderNotificationsPanel(el, ctx) {
  el.innerHTML = `
    <div class="aisb-btn-row">
      <button id="aisb-notif-refresh">更新</button>
      <button id="aisb-notif-read-all" class="aisb-btn-secondary">全て既読にする</button>
    </div>
    <div id="aisb-notif-list">読込中...</div>
  `;
  const listEl = el.querySelector("#aisb-notif-list");
  const levelLabel = { info: "情報", warning: "注意", critical: "重大" };

  function load() {
    listEl.textContent = "読込中...";
    fetch(`${ctx.API_BASE}/api/notifications`)
      .then((r) => r.json())
      .then((items) => {
        listEl.innerHTML =
          items
            .map(
              (n) => `<div class="aisb-card aisb-risk-${n.level === "critical" ? "overdue" : n.level === "warning" ? "due_soon" : "on_track"}${n.read ? "" : " aisb-notif-unread"}" data-id="${n.id}">
            <b>${n.title}</b><span class="aisb-risk-tag">${levelLabel[n.level] || n.level}</span><br>
            ${n.message}<br>
            <span class="aisb-event-time">${new Date(n.created_at).toLocaleString()} / ${n.source}</span>
            ${n.read ? "" : '<button class="aisb-notif-read-btn">既読にする</button>'}
          </div>`
            )
            .join("") || "<p>通知はありません</p>";
        listEl.querySelectorAll(".aisb-notif-read-btn").forEach((btn) => {
          btn.addEventListener("click", (ev) => {
            const id = ev.target.closest(".aisb-card").dataset.id;
            fetch(`${ctx.API_BASE}/api/notifications/${id}/read`, { method: "POST" })
              .then(() => {
                load();
                ctx.refreshUnreadBadge();
              })
              .catch((e) => alert(`エラー: ${e}`));
          });
        });
      })
      .catch((e) => (listEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  el.querySelector("#aisb-notif-refresh").addEventListener("click", load);
  el.querySelector("#aisb-notif-read-all").addEventListener("click", () => {
    fetch(`${ctx.API_BASE}/api/notifications/read-all`, { method: "POST" })
      .then(() => {
        load();
        ctx.refreshUnreadBadge();
      })
      .catch((e) => alert(`エラー: ${e}`));
  });

  load();
};
