// modules/panel-alerts.js — アラートパネル(README 4.3 panel-alerts.js相当)
// POST /api/push/check(在庫異常+AR/AP高リスクの集約アラート)。
//
// README 5.4.9 の Web Push(Service Worker + PushManager購読)は、実ブラウザ通知配信基盤
// (VAPID鍵/Service Worker push イベント)まで構築しないと動かず、この拡張は現状
// Service Workerをbackground.jsのメッセージ中継用途にしか使っていない。ここでは
// PushSubscription作成/削除のAPI自体は既に実装済み(Task#3)なので、実配信は行わず
// 「このブラウザを購読済み端末として登録する(endpointはローカル生成のダミー値)」
// までを実装する。実プッシュ配信を実装する場合は別途Service Worker側の対応が必要。
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.alerts = function renderAlertsPanel(el, ctx) {
  const severityClass = { high: "overdue", medium: "due_soon", info: "on_track" };
  const severityLabel = { high: "重要", medium: "注意", info: "参考" };

  el.innerHTML = `
    <div class="aisb-btn-row">
      <button id="aisb-alert-check">アラートを確認</button>
    </div>
    <div id="aisb-alert-result"></div>
    <div class="aisb-btn-row">
      <button id="aisb-alert-insight-btn" class="aisb-btn-secondary">AIで対応優先度を解釈する</button>
    </div>
    <div id="aisb-alert-insight"></div>
    <div class="aisb-section-title">通知購読</div>
    <div id="aisb-alert-sub-status" class="aisb-card"></div>
    <div class="aisb-btn-row">
      <button id="aisb-alert-sub" class="aisb-btn-secondary">この端末を購読する</button>
      <button id="aisb-alert-unsub" class="aisb-btn-secondary">購読解除</button>
    </div>
  `;
  const resultEl = el.querySelector("#aisb-alert-result");
  const statusEl = el.querySelector("#aisb-alert-sub-status");

  el.querySelector("#aisb-alert-insight-btn").addEventListener("click", (e) =>
    ctx.runInsight(`${ctx.API_BASE}/api/push/check/insight`, e.target, el.querySelector("#aisb-alert-insight"))
  );

  function endpointKey() {
    let ep = localStorage.getItem("aisb-push-endpoint");
    if (!ep) {
      ep = `local:${crypto.randomUUID()}`;
      localStorage.setItem("aisb-push-endpoint", ep);
    }
    return ep;
  }

  function renderSubStatus() {
    const subscribed = localStorage.getItem("aisb-push-subscribed") === "1";
    statusEl.textContent = subscribed ? "この端末は購読中です" : "未購読です";
  }

  el.querySelector("#aisb-alert-check").addEventListener("click", (e) => {
    const btn = e.target;
    btn.disabled = true;
    resultEl.textContent = "確認中...";
    fetch(`${ctx.API_BASE}/api/push/check`, { method: "POST" })
      .then((r) => r.json())
      .then((data) => {
        const alerts = data.alerts || [];
        resultEl.innerHTML =
          `<div class="aisb-badge">重要:${data.high_count}件 / 注意:${data.medium_count}件(全${data.total_alerts}件)</div>` +
          (data.summary ? `<div class="aisb-card aisb-summary-card">${ctx.escapeHtml(data.summary)}</div>` : "") +
          (alerts
            .map(
              (a) => `<div class="aisb-card aisb-risk-${severityClass[a.severity] || "on_track"}">
            <b>${ctx.escapeHtml(a.title)}</b><span class="aisb-risk-tag">${severityLabel[a.severity] || a.severity}</span><br>
            ${ctx.escapeHtml(a.message)}
          </div>`
            )
            .join("") || "<p>現在アラートはありません</p>");
      })
      .catch((e) => (resultEl.innerHTML = `<p>エラー: ${e}</p>`))
      .finally(() => (btn.disabled = false));
  });

  el.querySelector("#aisb-alert-sub").addEventListener("click", () => {
    ctx
      .postJson(`${ctx.API_BASE}/api/push/subscribe`, {
        endpoint: endpointKey(),
        device_name: navigator.userAgent.slice(0, 40),
      })
      .then(() => {
        localStorage.setItem("aisb-push-subscribed", "1");
        renderSubStatus();
      })
      .catch((e) => alert(`エラー: ${e}`));
  });

  el.querySelector("#aisb-alert-unsub").addEventListener("click", () => {
    ctx
      .postJson(`${ctx.API_BASE}/api/push/unsubscribe`, { endpoint: endpointKey() })
      .then(() => {
        localStorage.setItem("aisb-push-subscribed", "0");
        renderSubStatus();
      })
      .catch((e) => alert(`エラー: ${e}`));
  });

  renderSubStatus();
};
