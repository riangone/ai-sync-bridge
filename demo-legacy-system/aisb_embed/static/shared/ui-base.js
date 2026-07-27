// shared/ui-base.js — 埋め込み版
// chrome-extension/shared/ui-base.js の移植版。差分:
//   - CSSはインライン<style>ではなく<link rel="stylesheet">で読み込む
//   - 幅/開閉状態の永続化は chrome.storage.local ではなく localStorage
//     (configBase.saveJSON経由、同期的)
//   - 開閉(トグル/閉じる)状態もページ遷移をまたいで保持する(拡張版にはなかったが、
//     localStorageが常に使える環境かつページ遷移型のレガシー画面と相性が良いため追加)
//   - chrome.runtime.onMessage 相当の配線は無い(該当popupが存在しないため)
window.AISB = window.AISB || {};

window.AISB.uiBase = (function () {
  const MIN_WIDTH = 300;
  const MAX_WIDTH_RATIO = 0.9;

  function initShell({ profile, sidebarOpen, panels, ctx }) {
    const host = document.createElement("div");
    host.id = "aisb-host";
    host.style.setProperty("--aisb-width", `${profile.sidebarWidthPx}px`);
    document.documentElement.appendChild(host);
    const shadow = host.attachShadow({ mode: "closed" });

    const linkEl = document.createElement("link");
    linkEl.rel = "stylesheet";
    linkEl.href = "/aisb-embed/static/sidebar.css";
    shadow.appendChild(linkEl);

    const root = document.createElement("div");
    root.id = "aisb-root";
    root.className = sidebarOpen === false ? "aisb-collapsed" : "";
    shadow.appendChild(root);

    const panelDefs = (profile.panels || []).filter((p) => p.enabled);

    root.innerHTML = `
      <div id="aisb-toggle" title="AI-Sync Bridge">🤖</div>
      <div id="aisb-panel">
        <div id="aisb-resize-handle" title="ドラッグして幅を調整"></div>
        <div id="aisb-header">
          <span>AI-Sync Bridge</span>
          <div id="aisb-header-btns">
            <button id="aisb-minimize" title="最小化">–</button>
            <button id="aisb-maximize" title="最大化/元に戻す">⛶</button>
            <button id="aisb-close" title="閉じる">×</button>
          </div>
        </div>
        <div id="aisb-tabs">
          ${panelDefs.map((p, i) => `<button class="aisb-tab${i === 0 ? " active" : ""}" data-panel="${p.id}">${p.label}</button>`).join("")}
        </div>
        <div id="aisb-body"></div>
      </div>
    `;

    const bodyEl = root.querySelector("#aisb-body");
    const tabButtons = [...root.querySelectorAll(".aisb-tab")];

    const panelEls = {};
    function showPanel(id) {
      tabButtons.forEach((b) => b.classList.toggle("active", b.dataset.panel === id));
      Object.entries(panelEls).forEach(([pid, paneEl]) => {
        paneEl.style.display = pid === id ? "" : "none";
      });
      if (!panelEls[id]) {
        const paneEl = document.createElement("div");
        paneEl.className = "aisb-panel-pane";
        paneEl.dataset.panel = id;
        bodyEl.appendChild(paneEl);
        panelEls[id] = paneEl;
        const renderer = panels[id] || renderUnknownPanel;
        renderer(paneEl, ctx);
      }
    }
    tabButtons.forEach((b) => b.addEventListener("click", () => showPanel(b.dataset.panel)));
    if (panelDefs[0]) showPanel(panelDefs[0].id);

    // ---- 幅リサイズ(ドラッグ) ----
    const resizeHandle = root.querySelector("#aisb-resize-handle");
    let resizing = false;
    let latestWidth = profile.sidebarWidthPx || 380;

    resizeHandle.addEventListener("mousedown", (e) => {
      if (root.classList.contains("aisb-maximized")) return;
      resizing = true;
      resizeHandle.classList.add("aisb-resizing");
      document.body.style.userSelect = "none";
      e.preventDefault();
    });
    window.addEventListener("mousemove", (e) => {
      if (!resizing) return;
      const maxWidth = Math.min(900, window.innerWidth * MAX_WIDTH_RATIO);
      const newWidth = Math.min(Math.max(window.innerWidth - e.clientX, MIN_WIDTH), maxWidth);
      latestWidth = newWidth;
      host.style.setProperty("--aisb-width", `${newWidth}px`);
    });
    window.addEventListener("mouseup", () => {
      if (!resizing) return;
      resizing = false;
      resizeHandle.classList.remove("aisb-resizing");
      document.body.style.userSelect = "";
      ctx.persistWidth(Math.round(latestWidth));
    });

    // ---- 最小化(ヘッダーのみに折りたたむ) / 最大化(広い固定幅) ----
    root.querySelector("#aisb-minimize").addEventListener("click", () => {
      root.classList.remove("aisb-maximized");
      root.classList.toggle("aisb-minimized");
    });
    root.querySelector("#aisb-maximize").addEventListener("click", () => {
      root.classList.remove("aisb-minimized");
      root.classList.toggle("aisb-maximized");
    });

    // ---- 通知タブに未読件数バッジを表示する ----
    const notifTab = tabButtons.find((b) => b.dataset.panel === "notifications");
    function refreshUnreadBadge() {
      if (!notifTab) return;
      fetch(`${ctx.API_BASE}/api/notifications/unread-count`)
        .then((r) => r.json())
        .then((data) => {
          const label = panelDefs.find((p) => p.id === "notifications")?.label || "通知";
          notifTab.textContent = data.unread_count > 0 ? `${label} (${data.unread_count})` : label;
        })
        .catch(() => {});
    }
    if (notifTab) {
      refreshUnreadBadge();
      setInterval(refreshUnreadBadge, 15000);
    }
    ctx.refreshUnreadBadge = refreshUnreadBadge;

    // 開閉状態はページ遷移をまたいで保持する(localStorageが常に使える環境かつ
    // ページ遷移型のレガシー画面と相性が良いため、拡張版にはない永続化を追加している)。
    root.querySelector("#aisb-toggle").addEventListener("click", () => {
      root.classList.toggle("aisb-collapsed");
      window.AISB.configBase.saveJSON(window.AISB.configBase.STORAGE_KEY_OPEN, !root.classList.contains("aisb-collapsed"));
    });
    root.querySelector("#aisb-close").addEventListener("click", () => {
      root.classList.add("aisb-collapsed");
      window.AISB.configBase.saveJSON(window.AISB.configBase.STORAGE_KEY_OPEN, false);
    });

    return { host, shadow, root, showPanel };
  }

  function renderUnknownPanel(el) {
    el.innerHTML = `<p>未対応パネルです。</p>`;
  }

  return { initShell };
})();
