// shared/ui-base.js
// サイドバーの外枠(Shadow DOM/ヘッダー/タブ/リサイズ/最小化最大化/開閉/未読バッジ)を
// 組み立てる。パネルの中身は関与しない(modules/panel-*.js の責務)。
window.AISB = window.AISB || {};

window.AISB.uiBase = (function () {
  const MIN_WIDTH = 300;
  const MAX_WIDTH_RATIO = 0.9;

  // profile/sidebarOpen/CSS/panels(レンダラーのマップ)/ctx(各パネルへ渡す共有コンテキスト)を
  // 受け取り、Shadow DOM を構築してイベントを配線する。ctx は呼び出し側(bootstrap.js)が
  // 生成したオブジェクトをそのまま渡してもらい、ここで ctx.refreshUnreadBadge を追加で
  // セットして返す(通知パネルが既読化後に呼べるようにするため)。
  function initShell({ profile, sidebarOpen, CSS, panels, ctx }) {
    const host = document.createElement("div");
    host.id = "aisb-host";
    host.style.setProperty("--aisb-width", `${profile.sidebarWidthPx}px`);
    document.documentElement.appendChild(host);
    const shadow = host.attachShadow({ mode: "closed" });

    const styleEl = document.createElement("style");
    styleEl.textContent = CSS;
    shadow.appendChild(styleEl);

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

    // パネル切替時に前回の表示内容(取得済みデータ・入力途中の値・スクロール位置)を
    // 保持するため、タブごとのpaneはbodyEl配下に残したまま display:none で
    // 出し入れするだけにする(毎回innerHTML=""で作り直すと再フェッチ&状態リセットされる)。
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

    // ---- 通知タブに未読件数バッジを表示する(ワークフロー発火等をリアルタイムに気づけるように) ----
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

    root.querySelector("#aisb-toggle").addEventListener("click", () => {
      root.classList.toggle("aisb-collapsed");
    });
    root.querySelector("#aisb-close").addEventListener("click", () => {
      root.classList.add("aisb-collapsed");
    });

    return { host, shadow, root, showPanel };
  }

  function renderUnknownPanel(el) {
    el.innerHTML = `<p>未対応パネルです。</p>`;
  }

  return { initShell };
})();
