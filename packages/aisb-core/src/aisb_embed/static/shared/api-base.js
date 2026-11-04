// shared/api-base.js
// API_BASE(ai-api-server)/LEGACY_ORIGIN(レガシー同一オリジンJSON API)への
// 呼び出しをまとめる薄いクライアント層。各 modules/panel-*.js はこの
// createClient() が返すオブジェクトを ctx 経由で受け取って使う。
window.AISB = window.AISB || {};

window.AISB.apiBase = (function () {
  function createClient(API_BASE, LEGACY_ORIGIN, escapeHtml) {
    // 統計/ルール評価の結果をAIに解釈させる各パネル共通のボタン挙動。
    // 分析(予測分析)/ワークフロー(発火傾向)/管理(統計コメント)の3箇所で使い回す。
    // GET専用(サーバー側で対象データを取り直して都度プロンプトを組み立てるため、bodyは不要)。
    async function runInsight(url, btn, outEl) {
      btn.disabled = true;
      const prevLabel = btn.textContent;
      btn.textContent = "AI解釈を生成中...";
      outEl.innerHTML = "";
      try {
        const res = await fetch(url);
        const data = await res.json();
        outEl.innerHTML = `<div class="aisb-card aisb-insight-card">${escapeHtml(data.comment)}</div>`;
      } catch (e) {
        outEl.innerHTML = `<p>エラー: ${e}</p>`;
      } finally {
        btn.disabled = false;
        btn.textContent = prevLabel;
      }
    }

    async function postJson(url, body) {
      const res = await fetch(url, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        let detail = "";
        try {
          detail = (await res.json()).detail || "";
        } catch (e) {
          /* レスポンスがJSONでない場合は無視 */
        }
        throw new Error(`HTTP ${res.status}${detail ? `: ${detail}` : ""}`);
      }
      return res.json();
    }

    return { API_BASE, LEGACY_ORIGIN, runInsight, postJson };
  }

  return { createClient };
})();
