// modules/panel-a2a.js — A2A (Agent-to-Agent) システム間連携の専用デモタブ
//
// 見せたいこと:
//   1. 2つの独立したシステム(ERP / CRM)が DB 非共有のまま A2A プロトコルで協調回答する
//   2. Agent の発見(bridge.yaml ホワイトリスト + /.well-known/agent.json)と
//      安全な関連付け(Peer APIキー + 呼び出し側 allowed_roles + 相手側最小権限 ACL)を可視化
//   3. ロールごとの委譲上限(営業/管理者は可、経理/人事は方針で委譲不可)と
//      相手側での機密データ除外(ACL filtered)および独立した監査IDを確認できる
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.a2a = function renderA2APanel(el, ctx) {
  const esc = ctx.escapeHtml;
  const ME = window.AISB_DEMO_ROLE || null;

  const SCENARIOS = [
    {
      label: "📦 注文遅延＋クレーム横断",
      desc: "ERPの受注(ORD1015)とCRMのクレーム履歴を横断確認",
      q: "山田商事の注文 ORD1015 の状況とクレーム履歴を教えて",
    },
    {
      label: "🔒 機密契約の隔離確認",
      desc: "CRM側の機密契約(違約金)がACLで除外され漏洩しないことを確認",
      q: "山田商事の機密契約にある違約金条項（何%か）を教えて",
    },
    {
      label: "🏢 VIP顧客の取引状況",
      desc: "ERPの取引情報とCRMの顧客ランクを統合確認",
      q: "山田商事の取引状況と顧客ランクを教えて",
    },
  ];

  el.innerHTML = `
    <div style="font-size:12px;color:#444;line-height:1.6;margin-bottom:8px">
      <b>A2A (Agent-to-Agent) 連携</b>: 自システム(ERP)と別システム(CRM)を<b>DB非共有</b>のまま連携し、質問だけを委譲して結論を受け取ります。
    </div>

    <div id="aisb-a2a-status" class="aisb-card" style="font-size:12px;margin-bottom:8px">
      <div style="color:#888">連携先 Agent の状態を確認中...</div>
    </div>

    <details id="aisb-a2a-how" class="aisb-card" style="font-size:11.5px;line-height:1.6;margin-bottom:8px;cursor:pointer">
      <summary style="font-weight:700;color:#1e3a5f">🔍 2つのAgentはどう発見し、安全に連携するのか？</summary>
      <div style="margin-top:6px;color:#333;cursor:auto">
        <div style="margin-bottom:5px"><b>① 発見 (Discovery)</b>: 管理者が <code>bridge.yaml</code> に信頼済み Peer を事前登録（ホワイトリスト）。各 Agent は <code>GET /.well-known/agent.json</code>（AgentCard）で能力とエンドポイントを公開します。</div>
        <div style="margin-bottom:5px"><b>② 認証 (Peer Key)</b>: Agent 間通信は環境変数管理の専用 Peer キー（リポジトリ非保存）で認証。匿名アクセスは <code>401</code> で即拒否されます。</div>
        <div style="margin-bottom:5px"><b>③ 二重の権限境界</b>:
          <ul style="margin:2px 0 0 16px;padding:0">
            <li><b>呼び出し側(ERP)の委譲上限</b>: <code>allowed_roles</code> で委譲できるロールを制限（例: 営業・管理者は可、人事・経理は不可）。</li>
            <li><b>受け取り側(CRM)の最小権限ACL</b>: ERP 用 Peer キーに紐づく権限のみで回答。機密契約（違約金等）は相手側で自動除外されます。</li>
          </ul>
        </div>
        <div><b>④ DB非共有・独立監査</b>: 相手の DB には一切触れず、注文番号(<code>ORD1015</code>)等の業務キーを含む質問だけを送信。双方に独立したハッシュチェーン監査IDが残ります。</div>
      </div>
    </details>

    <div style="font-size:11px;color:#555;margin-bottom:4px">デモシナリオ（クリックで入力＆実行）:</div>
    <div id="aisb-a2a-chips" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
      ${SCENARIOS.map(
        (s, idx) =>
          `<button type="button" class="aisb-a2a-chip" data-idx="${idx}" title="${esc(s.desc)}" style="font-size:11px;padding:3px 8px">${esc(s.label)}</button>`,
      ).join("")}
    </div>

    <div id="aisb-a2a-row" style="display:flex;gap:4px;margin-bottom:8px">
      <input id="aisb-a2a-q" type="text" value="${esc(SCENARIOS[0].q)}" placeholder="システム横断で質問を入力..." style="flex:1" />
      <button id="aisb-a2a-run" type="button">A2A連携回答</button>
    </div>

    <div id="aisb-a2a-results"></div>
  `;

  const $ = (s) => el.querySelector(s);
  let peerInfo = { enabled: false, agent: "", peers: [] };
  let reqSeq = 0;

  function refLabel(r) {
    return `<span class="aisb-badge">${esc(r.entity)}</span> ${esc(r.title || r.pk)}`;
  }

  async function loadPeers() {
    const statusEl = $("#aisb-a2a-status");
    const qs = ME ? `?persona=${encodeURIComponent(ME.id)}` : "";
    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/peers${qs}`);
      const d = await res.json().catch(() => ({}));
      if (!res.ok || !d.enabled) {
        statusEl.innerHTML = `<span style="color:#888">この環境では A2A 連携が無効になっています。</span>`;
        $("#aisb-a2a-run").disabled = true;
        return;
      }
      peerInfo = d;
      const peerRows = (d.peers || [])
        .map((p) => {
          const badge = p.allowed
            ? `<span style="background:#e6f7ec;color:#0a7d34;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">委譲許可</span>`
            : `<span style="background:#f3f4f6;color:#666;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">方針により委譲不可</span>`;
          return `<div style="margin-top:4px;padding-top:4px;border-top:1px solid #eee">
            <b>Peer: ${esc(p.name.toUpperCase())} Agent</b> ${badge}
            <div style="font-size:11px;color:#666">${esc(p.description || "")}</div>
          </div>`;
        })
        .join("");

      statusEl.innerHTML = `
        <div><b>自Agent</b>: ${esc(d.agent || "ERP Agent")} ${ME ? `<span class="aisb-badge">${esc(ME.label)}</span>` : ""}</div>
        ${peerRows || `<div style="color:#888;font-size:11px">登録済み Peer はありません</div>`}
      `;
    } catch (e) {
      statusEl.innerHTML = `<span style="color:#d03b3b">接続情報の取得に失敗: ${esc(e.message)}</span>`;
    }
  }

  async function runA2A() {
    const q = $("#aisb-a2a-q").value.trim();
    const out = $("#aisb-a2a-results");
    if (!q) return;
    if (!ME) {
      out.innerHTML = `<div class="aisb-card" style="color:#d03b3b">ロールを選択してから実行してください。</div>`;
      return;
    }
    const seq = ++reqSeq;
    const peerNames = (peerInfo.peers || []).map((p) => p.name.toUpperCase()).join(", ") || "Peer";
    out.innerHTML = `<div class="aisb-card"><b>A2A 連携回答を実行中...</b>
      <div style="color:#666;font-size:11.5px;margin-top:4px">① 自システム(${esc(peerInfo.agent || "ERP")})の権限検索と、② ${esc(peerNames)} Agent への A2A 質問委譲を並列実行しています...</div></div>`;

    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/federated-ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona: ME.id, question: q }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(`${res.status} ${d.detail || ""}`.trim());
      if (seq !== reqSeq) return;

      const loc = d.local || {};
      const cites = (loc.citations || []).map((c) => `<li>[${esc(String(c.n))}] ${refLabel(c)}</li>`).join("");

      let html = `
        <div class="aisb-card" style="border-left:3px solid #2563eb">
          <div><b>① ${esc(d.agent || "自システム (ERP)")}</b> <span style="color:#666;font-size:11px">(${esc(ME.label)}の権限で回答)</span></div>
          <div style="white-space:pre-wrap;font-size:12px;margin:6px 0">${esc(loc.answer || "(回答なし)")}</div>
          <div style="font-size:11px;color:#666">権限で除外: <b>${esc(String(loc.acl_filtered ?? 0))}</b> 件 · 監査ID: <code>${esc(String(loc.audit_id || "").slice(0, 8))}</code></div>
          ${cites ? `<ul style="margin:4px 0 0 16px;padding:0;font-size:11px">${cites}</ul>` : ""}
        </div>`;

      html += (d.peers || [])
        .map((p) => {
          const head = `<b>② ${esc(p.peer.toUpperCase())} Agent</b> <span class="aisb-badge">A2A</span>`;
          if (p.status === "forbidden") {
            return `<div class="aisb-card" style="border-left:3px solid #9ca3af">
              <div>${head} <span style="font-size:11px;color:#666">委譲ブロック</span></div>
              <div style="font-size:12px;color:#555;margin-top:4px">${esc(ME.label)}ロールは ${esc(p.peer.toUpperCase())} への委譲が許可されていないため、相手システムには問い合わせていません（<code>bridge.yaml</code> の <code>allowed_roles</code> で制御）。</div>
            </div>`;
          }
          const ok = p.status === "completed";
          return `<div class="aisb-card" style="border-left:3px solid ${ok ? "#0ca30c" : "#d03b3b"}">
            <div>${head} <span style="font-size:11px;color:${ok ? "#0ca30c" : "#d03b3b"}">${esc(p.status)}</span></div>
            <div style="white-space:pre-wrap;font-size:12px;margin:6px 0">${esc(p.answer || p.error || "(応答なし)")}</div>
            ${
              ok
                ? `<div style="font-size:11px;color:#666">相手側ACLで除外: <b>${esc(String(p.acl_filtered ?? 0))}</b> 件 · 相手側監査ID: <code>${esc(String(p.audit_id || "").slice(0, 8))}</code><br>※ 相手のDBには触れず、相手Agentが最小権限で生成した結論のみを受信しています。</div>`
                : ""
            }
          </div>`;
        })
        .join("");

      out.innerHTML = html;
    } catch (e) {
      if (seq !== reqSeq) return;
      out.innerHTML = `<div class="aisb-card" style="color:#d03b3b">エラー: ${esc(e.message)}</div>`;
    }
  }

  $("#aisb-a2a-run").addEventListener("click", runA2A);
  $("#aisb-a2a-q").addEventListener("keydown", (e) => e.key === "Enter" && runA2A());
  el.querySelectorAll(".aisb-a2a-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = SCENARIOS[Number(btn.dataset.idx)];
      if (!s) return;
      $("#aisb-a2a-q").value = s.q;
      runA2A();
    });
  });

  loadPeers();
};
