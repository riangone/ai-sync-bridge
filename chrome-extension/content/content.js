// AI-Sync Bridge content script
// レガシーページに Shadow DOM (mode: 'closed') でサイドバーを注入する。
// ホストページのCSS/JSと完全に分離し、幅は CSS変数で制御する。

// content/sidebar.css のインライン複製。
// 理由: chrome.runtime.getURL()+fetch() によるランタイム読み込みは
// 拡張コンテキスト無効化のタイミング次第で "chrome-extension://invalid/"
// エラーを起こし、CSSが適用されないことがあった。ビルドプロセスを持たない
// この拡張では、ファイルを分けたままJS文字列としてインライン化するのが
// 最も単純で確実な回避策。sidebar.css を編集したら、必ずこの定数にも
// 同じ内容を反映すること。
const AISB_SIDEBAR_CSS = `
/* Shadow DOM 内スタイル。ホストページに一切影響を与えない */
:host, #aisb-root {
  all: initial;
}
#aisb-root * {
  box-sizing: border-box;
  font-family: -apple-system, "Segoe UI", "Hiragino Sans", sans-serif;
}
#aisb-toggle {
  position: fixed;
  top: 50%;
  right: 0;
  transform: translateY(-50%);
  background: #3a6ea5;
  color: #fff;
  width: 36px;
  height: 36px;
  border-radius: 50% 0 0 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 18px;
  z-index: 2147483647;
  box-shadow: -2px 0 6px rgba(0,0,0,0.3);
}
#aisb-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: var(--aisb-width, 380px);
  height: 100vh;
  background: #fff;
  box-shadow: -4px 0 16px rgba(0,0,0,0.25);
  display: flex;
  flex-direction: column;
  z-index: 2147483646;
  transition: transform 0.2s ease;
}
.aisb-collapsed #aisb-panel {
  transform: translateX(100%);
}
#aisb-header {
  background: #1c3f61;
  color: #fff;
  padding: 10px 14px;
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-weight: 600;
}
#aisb-header button {
  background: transparent;
  border: none;
  color: #fff;
  font-size: 18px;
  cursor: pointer;
}
#aisb-tabs {
  display: flex;
  border-bottom: 1px solid #ddd;
  background: #f7f7f9;
}
.aisb-tab {
  flex: 1;
  padding: 8px 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 12px;
  color: #555;
  border-bottom: 2px solid transparent;
}
.aisb-tab.active {
  color: #1c3f61;
  border-bottom-color: #3a6ea5;
  font-weight: 600;
}
#aisb-body {
  flex: 1;
  overflow-y: auto;
  padding: 12px;
  font-size: 13px;
  color: #222;
}
.aisb-card {
  background: #f5f7fa;
  border: 1px solid #e0e4e8;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 8px;
  font-size: 12px;
  line-height: 1.5;
}
.aisb-badge {
  display: inline-block;
  background: #e8f0fe;
  color: #1c3f61;
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  margin-bottom: 8px;
}
#aisb-chat-log {
  height: calc(100vh - 220px);
  overflow-y: auto;
  margin-bottom: 8px;
}
.aisb-msg {
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 8px;
  max-width: 90%;
  font-size: 12px;
  line-height: 1.5;
}
.aisb-msg-user {
  background: #3a6ea5;
  color: #fff;
  margin-left: auto;
}
.aisb-msg-assistant {
  background: #eef1f4;
  color: #222;
}
#aisb-chat-input-row, #aisb-search-row {
  display: flex;
  gap: 6px;
}
#aisb-chat-input, #aisb-search-input {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid #ccc;
  border-radius: 4px;
  font-size: 12px;
}
#aisb-chat-send, #aisb-search-run, #aisb-ocr-run {
  background: #3a6ea5;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 12px;
}
#aisb-ocr-result {
  background: #f5f7fa;
  border: 1px solid #e0e4e8;
  border-radius: 6px;
  padding: 8px;
  margin-top: 8px;
  font-size: 11px;
  white-space: pre-wrap;
  max-height: 60vh;
  overflow-y: auto;
}

/* ---- Analytics (Chart.js 等の外部ライブラリを使わず、純CSSバーチャートで表現) ---- */
.aisb-chart {
  display: flex;
  align-items: flex-end;
  gap: 4px;
  height: 120px;
  padding: 8px 4px 0;
  border-bottom: 1px solid #ddd;
  margin-bottom: 6px;
}
.aisb-bar-col {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: flex-end;
  height: 100%;
  gap: 4px;
}
.aisb-bar {
  width: 100%;
  border-radius: 3px 3px 0 0;
  background: #3a6ea5;
}
.aisb-bar.aisb-bar-forecast {
  background: repeating-linear-gradient(45deg, #9db8d6, #9db8d6 4px, #c3d4e8 4px, #c3d4e8 8px);
}
.aisb-bar-label {
  font-size: 9px;
  color: #666;
  writing-mode: vertical-rl;
  text-orientation: mixed;
}
.aisb-legend {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: #555;
  margin-bottom: 10px;
}
.aisb-legend-dot {
  display: inline-block;
  width: 9px;
  height: 9px;
  border-radius: 2px;
  margin-right: 4px;
  vertical-align: middle;
}

/* ---- 再受注リスク / ワークフロー ---- */
.aisb-risk-overdue { border-left: 4px solid #c0392b; }
.aisb-risk-due_soon { border-left: 4px solid #d68910; }
.aisb-risk-on_track { border-left: 4px solid #2e8b57; }
.aisb-risk-tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 600;
  padding: 1px 6px;
  border-radius: 3px;
  margin-left: 6px;
}
.aisb-risk-overdue .aisb-risk-tag { background: #fdecea; color: #c0392b; }
.aisb-risk-due_soon .aisb-risk-tag { background: #fdf2e0; color: #d68910; }
.aisb-risk-on_track .aisb-risk-tag { background: #e8f5ec; color: #2e8b57; }

.aisb-section-title {
  font-size: 12px;
  font-weight: 600;
  color: #1c3f61;
  margin: 10px 0 6px;
}
.aisb-btn-row {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}
.aisb-btn-row button {
  background: #3a6ea5;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 11px;
}
.aisb-btn-row button.aisb-btn-secondary {
  background: #eef1f4;
  color: #1c3f61;
}
.aisb-event-card {
  background: #fff8e6;
  border: 1px solid #f0dca0;
  border-radius: 6px;
  padding: 6px 8px;
  margin-bottom: 6px;
  font-size: 11px;
}
.aisb-event-time {
  color: #999;
  font-size: 10px;
  display: block;
  margin-top: 2px;
}

/* ---- 通知 / 管理 (Phase4) ---- */
.aisb-notif-unread {
  box-shadow: inset 3px 0 0 #3a6ea5;
  background: #eef4fb;
}
.aisb-notif-read-btn {
  margin-top: 6px;
  background: #3a6ea5;
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 3px 8px;
  cursor: pointer;
  font-size: 10px;
}
`;

(async function () {
  // 拡張機能が再読み込み/更新された後、そのタブがまだリロードされていない場合、
  // このcontent.jsインスタンスは古い（無効化された）拡張コンテキストに紐づいたまま残る。
  // その状態で chrome.runtime.getURL() 等を呼ぶと "chrome-extension://invalid/..." を返し
  // net::ERR_FAILED が発生する。実害はない(サイドバー自体は表示される)が、
  // コンソールにエラーが出続けるため、コンテキスト無効化を検知したら静かに終了する。
  if (!chrome.runtime?.id) {
    return;
  }

  let activeProfile, sidebarOpen;
  try {
    ({ activeProfile, sidebarOpen } = await chrome.storage.local.get([
      "activeProfile",
      "sidebarOpen",
    ]));
  } catch (e) {
    // "Extension context invalidated" 等。安全に処理を打ち切る。
    return;
  }
  const profile = activeProfile || {
    apiBaseUrl: "http://localhost:5011",
    sidebarWidthPx: 380,
    panels: [
      { id: "chat", label: "AIチャット", enabled: true },
      { id: "customers", label: "顧客検索", enabled: true },
      { id: "ocr", label: "OCR取込", enabled: true },
      { id: "search", label: "セマンティック検索", enabled: true },
      { id: "analytics", label: "予測分析", enabled: true },
      { id: "workflows", label: "ワークフロー", enabled: true },
      { id: "notifications", label: "通知", enabled: true },
      { id: "admin", label: "管理", enabled: true },
    ],
  };

  // legacyOrigin (このページの実オリジン) から対応するAPIオリジンを引く。
  // 保存済みprofile.apiBaseUrlはインストール時点の固定値のため、
  // 例えばサーバー機ではlocalhost想定で保存されていても、ユーザーが
  // 公開ドメイン https://aisync.0101.click 経由で自分のPCから開いている場合、
  // localhost:5011はユーザー自身のPCを指してしまい接続不能になる。
  // 実際に開いているorigin (location.origin) を優先して解決する。
  const ORIGIN_API_MAP = {
    "http://localhost:5010": "http://localhost:5011",
    "https://aisync.0101.click": "https://aisync-api.0101.click",
  };
  const API_BASE = ORIGIN_API_MAP[location.origin] || profile.apiBaseUrl;

  // ---- ホスト要素 + Shadow DOM (closed) ----
  const host = document.createElement("div");
  host.id = "aisb-host";
  host.style.setProperty("--aisb-width", `${profile.sidebarWidthPx}px`);
  document.documentElement.appendChild(host);
  const shadow = host.attachShadow({ mode: "closed" });

  // sidebar.css は runtime fetch (chrome.runtime.getURL + fetch) をやめ、
  // ビルド時にインライン化した文字列を直接使う。
  // 理由: getURL/fetchによる読み込みは、拡張コンテキストが「トップの
  // id チェック通過後・この行に到達するまでの間」に無効化された場合
  // (例: 開発中に chrome://extensions で再読み込みした瞬間とページの
  // document_idle 実行が重なるレース)、chrome.runtime.getURL() が
  // "chrome-extension://invalid/..." を返し、fetch が失敗する。
  // このfetch失敗はChromeがネットワーク層で無条件にコンソールへ出力する
  // ため、try/catchで囲んでも赤いエラーログ自体は消せず、かつCSSも
  // 適用されないままになっていた。インライン化によりfetch自体をなくし、
  // この経路のエラーとスタイル未適用を両方解消する。
  const styleEl = document.createElement("style");
  styleEl.textContent = AISB_SIDEBAR_CSS;
  shadow.appendChild(styleEl);

  const root = document.createElement("div");
  root.id = "aisb-root";
  root.className = sidebarOpen === false ? "aisb-collapsed" : "";
  shadow.appendChild(root);

  const panelDefs = (profile.panels || []).filter((p) => p.enabled);

  root.innerHTML = `
    <div id="aisb-toggle" title="AI-Sync Bridge">🤖</div>
    <div id="aisb-panel">
      <div id="aisb-header">
        <span>AI-Sync Bridge</span>
        <button id="aisb-close">×</button>
      </div>
      <div id="aisb-tabs">
        ${panelDefs.map((p, i) => `<button class="aisb-tab${i === 0 ? " active" : ""}" data-panel="${p.id}">${p.label}</button>`).join("")}
      </div>
      <div id="aisb-body"></div>
    </div>
  `;

  const bodyEl = root.querySelector("#aisb-body");
  const tabButtons = [...root.querySelectorAll(".aisb-tab")];

  const renderers = {
    chat: renderChatPanel,
    customers: renderCustomersPanel,
    ocr: renderOcrPanel,
    search: renderSearchPanel,
    analytics: renderAnalyticsPanel,
    workflows: renderWorkflowsPanel,
    notifications: renderNotificationsPanel,
    admin: renderAdminPanel,
  };

  function showPanel(id) {
    tabButtons.forEach((b) => b.classList.toggle("active", b.dataset.panel === id));
    bodyEl.innerHTML = "";
    (renderers[id] || renderUnknownPanel)(bodyEl);
  }

  tabButtons.forEach((b) => b.addEventListener("click", () => showPanel(b.dataset.panel)));
  if (panelDefs[0]) showPanel(panelDefs[0].id);

  // ---- 通知タブに未読件数バッジを表示する(ワークフロー発火等をリアルタイムに気づけるように) ----
  const notifTab = tabButtons.find((b) => b.dataset.panel === "notifications");
  function refreshUnreadBadge() {
    if (!notifTab) return;
    fetch(`${API_BASE}/api/notifications/unread-count`)
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

  root.querySelector("#aisb-toggle").addEventListener("click", () => {
    root.classList.toggle("aisb-collapsed");
  });
  root.querySelector("#aisb-close").addEventListener("click", () => {
    root.classList.add("aisb-collapsed");
  });

  chrome.runtime.onMessage.addListener((msg) => {
    if (msg.type === "TOGGLE_SIDEBAR") {
      root.classList.toggle("aisb-collapsed", !msg.value);
    }
  });

  // ---------------- Panels ----------------
  function renderUnknownPanel(el) {
    el.innerHTML = `<p>未対応パネルです。</p>`;
  }

  function renderChatPanel(el) {
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
        const res = await fetch(`${API_BASE}/api/chat`, {
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
  }

  function renderCustomersPanel(el) {
    el.innerHTML = `<div id="aisb-customers-list">読込中...</div>`;
    const list = el.querySelector("#aisb-customers-list");
    fetch(`${API_BASE}/api/customers`)
      .then((r) => r.json())
      .then((rows) => {
        list.innerHTML = rows
          .map((c) => `<div class="aisb-card"><b>${c.name}</b><br>${c.company || ""}<br>${c.email || ""}</div>`)
          .join("") || "<p>顧客データがありません</p>";
      })
      .catch((e) => (list.innerHTML = `<p>エラー: ${e}</p>`));
  }

  function renderOcrPanel(el) {
    el.innerHTML = `
      <input type="file" id="aisb-ocr-file" accept="image/*,application/pdf" />
      <button id="aisb-ocr-run">OCR実行</button>
      <pre id="aisb-ocr-result"></pre>
    `;
    el.querySelector("#aisb-ocr-run").addEventListener("click", async () => {
      const fileInput = el.querySelector("#aisb-ocr-file");
      const resultEl = el.querySelector("#aisb-ocr-result");
      if (!fileInput.files[0]) {
        resultEl.textContent = "ファイルを選択してください";
        return;
      }
      const fd = new FormData();
      fd.append("file", fileInput.files[0]);
      resultEl.textContent = "解析中...";
      try {
        const res = await fetch(`${API_BASE}/api/ocr`, { method: "POST", body: fd });
        const data = await res.json();
        resultEl.textContent = JSON.stringify(data, null, 2);
      } catch (e) {
        resultEl.textContent = `エラー: ${e}`;
      }
    });
  }

  function renderSearchPanel(el) {
    el.innerHTML = `
      <div id="aisb-search-row">
        <input id="aisb-search-input" type="text" placeholder="自然文/キーワードで検索..." />
        <button id="aisb-search-run">検索</button>
      </div>
      <div id="aisb-search-results"></div>
    `;
    async function run() {
      const q = el.querySelector("#aisb-search-input").value.trim();
      const resultsEl = el.querySelector("#aisb-search-results");
      if (!q) return;
      resultsEl.textContent = "検索中...";
      try {
        const res = await fetch(`${API_BASE}/api/search`, {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ query: q, top_k: 5 }),
        });
        const data = await res.json();
        resultsEl.innerHTML =
          `<div class="aisb-badge">backend: ${data.backend}</div>` +
          data.results.map((r) => `<div class="aisb-card"><b>${r.title}</b> (score ${r.score})<br>${r.snippet}</div>`).join("");
      } catch (e) {
        resultsEl.textContent = `エラー: ${e}`;
      }
    }
    el.querySelector("#aisb-search-run").addEventListener("click", run);
    el.querySelector("#aisb-search-input").addEventListener("keydown", (e) => e.key === "Enter" && run());
  }

  function renderAnalyticsPanel(el) {
    el.innerHTML = `
      <div class="aisb-section-title">売上予測(線形回帰)</div>
      <div id="aisb-forecast-chart">読込中...</div>
      <div class="aisb-section-title">再受注リスク予測</div>
      <div id="aisb-reorder-list">読込中...</div>
    `;
    const chartEl = el.querySelector("#aisb-forecast-chart");
    const reorderEl = el.querySelector("#aisb-reorder-list");
    const riskLabel = { overdue: "要フォロー", due_soon: "近日予定", on_track: "順調" };

    fetch(`${API_BASE}/api/analytics/forecast?months_ahead=3`)
      .then((r) => r.json())
      .then((data) => {
        const points = data.points || [];
        if (!points.length) {
          chartEl.innerHTML = "<p>受注データがありません</p>";
          return;
        }
        const max = Math.max(...points.map((p) => p.actual ?? p.predicted ?? 0), 1);
        chartEl.innerHTML =
          `<div class="aisb-legend">
             <span><span class="aisb-legend-dot" style="background:#3a6ea5"></span>実績</span>
             <span><span class="aisb-legend-dot" style="background:#9db8d6"></span>予測(${data.method})</span>
           </div>
           <div class="aisb-chart">` +
          points
            .map((p) => {
              const isForecast = p.actual === null || p.actual === undefined;
              const value = isForecast ? p.predicted : p.actual;
              const h = Math.max(4, Math.round((value / max) * 100));
              return `<div class="aisb-bar-col" title="${p.month}: ${Math.round(value).toLocaleString()}円">
                <div class="aisb-bar${isForecast ? " aisb-bar-forecast" : ""}" style="height:${h}%"></div>
                <div class="aisb-bar-label">${p.month.slice(2)}</div>
              </div>`;
            })
            .join("") +
          `</div>`;
      })
      .catch((e) => (chartEl.innerHTML = `<p>エラー: ${e}</p>`));

    fetch(`${API_BASE}/api/analytics/reorder-predictions`)
      .then((r) => r.json())
      .then((data) => {
        const preds = data.predictions || [];
        reorderEl.innerHTML =
          preds
            .map(
              (p) => `<div class="aisb-card aisb-risk-${p.risk}">
            <b>${p.customer_name}</b><span class="aisb-risk-tag">${riskLabel[p.risk] || p.risk}</span><br>
            前回受注: ${p.last_order_date} / 平均間隔: ${p.avg_interval_days}日<br>
            次回予測: ${p.expected_next_date} (${p.days_until_expected >= 0 ? `あと${p.days_until_expected}日` : `${-p.days_until_expected}日超過`})
          </div>`
            )
            .join("") || "<p>予測対象の受注履歴がありません</p>";
      })
      .catch((e) => (reorderEl.innerHTML = `<p>エラー: ${e}</p>`));
  }

  function renderWorkflowsPanel(el) {
    el.innerHTML = `
      <div class="aisb-section-title">自動化ルール</div>
      <div id="aisb-wf-rules">読込中...</div>
      <div class="aisb-btn-row">
        <button id="aisb-wf-run">ルールを評価する</button>
      </div>
      <div class="aisb-section-title">発火履歴</div>
      <div id="aisb-wf-history">読込中...</div>
    `;
    const rulesEl = el.querySelector("#aisb-wf-rules");
    const historyEl = el.querySelector("#aisb-wf-history");

    function loadRules() {
      fetch(`${API_BASE}/api/workflows/rules`)
        .then((r) => r.json())
        .then((rules) => {
          rulesEl.innerHTML =
            rules
              .map(
                (r) => `<div class="aisb-card">
              <b>${r.name}</b><br>
              条件: ${r.entity}.${r.field} ${r.operator} ${r.value} → ${r.action}
            </div>`
              )
              .join("") || "<p>ルールがありません</p>";
        })
        .catch((e) => (rulesEl.innerHTML = `<p>エラー: ${e}</p>`));
    }

    function loadHistory() {
      fetch(`${API_BASE}/api/workflows/history`)
        .then((r) => r.json())
        .then((events) => {
          historyEl.innerHTML =
            events
              .map(
                (ev) => `<div class="aisb-event-card">
              <b>${ev.rule_name}</b>: ${ev.message}
              <span class="aisb-event-time">${new Date(ev.triggered_at).toLocaleString()}</span>
            </div>`
              )
              .join("") || "<p>発火履歴はまだありません</p>";
        })
        .catch((e) => (historyEl.innerHTML = `<p>エラー: ${e}</p>`));
    }

    el.querySelector("#aisb-wf-run").addEventListener("click", async () => {
      historyEl.textContent = "評価中...";
      try {
        const res = await fetch(`${API_BASE}/api/workflows/run`, { method: "POST" });
        const data = await res.json();
        loadHistory();
        if (data.new_events.length === 0) {
          historyEl.insertAdjacentHTML("afterbegin", `<div class="aisb-badge">新規発火なし(全て評価済み)</div>`);
        }
      } catch (e) {
        historyEl.textContent = `エラー: ${e}`;
      }
    });

    loadRules();
    loadHistory();
  }

  function renderNotificationsPanel(el) {
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
      fetch(`${API_BASE}/api/notifications`)
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
              fetch(`${API_BASE}/api/notifications/${id}/read`, { method: "POST" })
                .then(() => {
                  load();
                  refreshUnreadBadge();
                })
                .catch((e) => alert(`エラー: ${e}`));
            });
          });
        })
        .catch((e) => (listEl.innerHTML = `<p>エラー: ${e}</p>`));
    }

    el.querySelector("#aisb-notif-refresh").addEventListener("click", load);
    el.querySelector("#aisb-notif-read-all").addEventListener("click", () => {
      fetch(`${API_BASE}/api/notifications/read-all`, { method: "POST" })
        .then(() => {
          load();
          refreshUnreadBadge();
        })
        .catch((e) => alert(`エラー: ${e}`));
    });

    load();
  }

  function renderAdminPanel(el) {
    el.innerHTML = `
      <div class="aisb-section-title">システム状況</div>
      <div id="aisb-admin-stats">読込中...</div>
      <div class="aisb-btn-row">
        <button id="aisb-admin-reset" class="aisb-btn-secondary">デモデータをリセット</button>
      </div>
      <div class="aisb-section-title">監査ログ</div>
      <div id="aisb-admin-audit">読込中...</div>
    `;
    const statsEl = el.querySelector("#aisb-admin-stats");
    const auditEl = el.querySelector("#aisb-admin-audit");

    function loadStats() {
      fetch(`${API_BASE}/api/admin/stats`)
        .then((r) => r.json())
        .then((s) => {
          statsEl.innerHTML = `
            <div class="aisb-card">
              モード: ${s.demo_mode ? "デモ" : "本番"} / AI: ${s.ai_provider} / 検索: ${s.vector_backend}<br>
              顧客数: ${s.customer_count} / 受注数: ${s.order_count}<br>
              ワークフロー: ルール${s.workflow_rule_count}件 / 発火${s.workflow_event_count}件<br>
              未読通知: ${s.unread_notification_count}件
            </div>`;
        })
        .catch((e) => (statsEl.innerHTML = `<p>エラー: ${e}</p>`));
    }

    function loadAudit() {
      fetch(`${API_BASE}/api/admin/audit-log`)
        .then((r) => r.json())
        .then((entries) => {
          auditEl.innerHTML =
            entries
              .map(
                (a) => `<div class="aisb-event-card">
              [${a.action}] ${a.detail}
              <span class="aisb-event-time">${new Date(a.at).toLocaleString()} (${a.actor})</span>
            </div>`
              )
              .join("") || "<p>監査ログはまだありません</p>";
        })
        .catch((e) => (auditEl.innerHTML = `<p>エラー: ${e}</p>`));
    }

    el.querySelector("#aisb-admin-reset").addEventListener("click", () => {
      if (!confirm("デモデータ(顧客/受注/会話履歴)を初期状態にリセットします。よろしいですか?")) return;
      fetch(`${API_BASE}/api/admin/reset-demo-data`, { method: "POST" })
        .then((r) => r.json())
        .then(() => {
          loadStats();
          loadAudit();
          refreshUnreadBadge();
        })
        .catch((e) => alert(`エラー: ${e}`));
    });

    loadStats();
    loadAudit();
  }
})();
