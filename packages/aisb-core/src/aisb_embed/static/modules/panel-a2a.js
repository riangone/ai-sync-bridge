// modules/panel-a2a.js — A2A (Agent-to-Agent) システム間連携 & ライフサイクル管理の専用デモタブ
//
// 2つのサブビューを提供:
//   1. 🤝 連携デモ: 3つの独立システム(ERP / CRM / 物流)が DB 非共有のまま協調回答・機密隔離を実演
//      (統合回答・ホップごとのトレース付き)
//   2. 🛡️ 発見・認証・管理: 定義・公開・一覧・探索・招待・認証・拒否・遮断の全ライフサイクルを実操作
window.AISB = window.AISB || {};
window.AISB.panels = window.AISB.panels || {};

window.AISB.panels.a2a = function renderA2APanel(el, ctx) {
  const esc = ctx.escapeHtml;
  const ME = window.AISB_DEMO_ROLE || null;

  const SCENARIOS = [
    {
      label: "🚚 3システム統合（ERP＋CRM＋物流）",
      desc: "受注(ERP)・クレーム(CRM)・出荷保留の理由(物流)を並列に委譲し、各Agentの結論だけから統合回答を作成",
      q: "山田商事の注文 ORD1015 はいつ届く？クレーム状況と、出荷が止まっている理由もまとめて",
      synthesize: true,
    },
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

  const PEER_LABEL = { crm: "CRM", logistics: "物流", erp: "ERP" };
  const PEER_PAGE = { crm: "/crm/", logistics: "/logistics/" };
  const peerLabel = (n) => PEER_LABEL[n] || String(n || "").toUpperCase();
  const STATUS_META = {
    active: { label: "連携中", bg: "#e6f7ec", fg: "#0a7d34" },
    invited: { label: "招待中", bg: "#eff6ff", fg: "#1d4ed8" },
    rejected: { label: "拒否済", bg: "#fef2f2", fg: "#b91c1c" },
    blocked: { label: "遮断中", bg: "#f3f4f6", fg: "#374151" },
  };

  el.innerHTML = `
    <div style="display:flex;gap:4px;margin-bottom:8px">
      <button type="button" class="aisb-a2a-subtab" data-sub="ask" style="flex:1;font-size:11.5px;font-weight:700;padding:5px 8px">🤝 連携デモ</button>
      <button type="button" class="aisb-a2a-subtab" data-sub="gov" style="flex:1;font-size:11.5px;font-weight:700;padding:5px 8px">🛡️ 発見・認証・管理</button>
    </div>

    <!-- サブビュー1: 連携デモ -->
    <div id="aisb-a2a-view-ask">
      <div style="font-size:12px;color:#444;line-height:1.6;margin-bottom:8px">
        <b>A2A (Agent-to-Agent) 連携</b>: 自システム(ERP)と別システム(CRM)を<b>DB非共有</b>のまま連携し、質問だけを委譲して結論を受け取ります。
      </div>

      <div id="aisb-a2a-status" class="aisb-card" style="font-size:12px;margin-bottom:8px">
        <div style="color:#888">連携先 Agent の状態を確認中...</div>
      </div>

      <div style="font-size:11px;color:#555;margin-bottom:4px">デモシナリオ（クリックで入力＆実行）:</div>
      <div id="aisb-a2a-chips" style="display:flex;flex-wrap:wrap;gap:4px;margin-bottom:8px">
        ${SCENARIOS.map(
          (s, idx) =>
            `<button type="button" class="aisb-a2a-chip" data-idx="${idx}" title="${esc(s.desc)}" style="font-size:11px;padding:3px 8px">${esc(s.label)}</button>`,
        ).join("")}
      </div>

      <div id="aisb-a2a-row" style="display:flex;gap:4px;margin-bottom:4px">
        <input id="aisb-a2a-q" type="text" value="${esc(SCENARIOS[0].q)}" placeholder="システム横断で質問を入力..." style="flex:1" />
        <button id="aisb-a2a-run" type="button">A2A連携回答</button>
      </div>
      <label style="display:flex;align-items:center;gap:4px;font-size:11px;color:#555;margin-bottom:8px">
        <input id="aisb-a2a-synth" type="checkbox" checked /> 各Agentの結論から<b>統合回答</b>を作る（相手の回答は「データ」として扱い、指示には従わない）
      </label>

      <div id="aisb-a2a-results"></div>
    </div>

    <!-- サブビュー2: 発見・認証・管理（ライフサイクル実操台） -->
    <div id="aisb-a2a-view-gov" style="display:none;font-size:11.5px">
      <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:6px">
        <span style="color:#444"><b>Agent ライフサイクル操作デモ</b></span>
        <button id="aisb-gov-reset" type="button" style="font-size:10.5px;padding:2px 8px">↺ 初期状態に戻す</button>
      </div>

      <!-- ① 定義 & 公開 -->
      <div class="aisb-card" style="margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>① 定義 ＆ 公開 (Define / Publish)</b>
          <span id="aisb-gov-pub-badge"></span>
        </div>
        <div style="color:#555;margin:4px 0">
          <code>bridge.yaml</code> で自Agentを定義し、<code>GET /.well-known/agent.json</code> の公開 ON/OFF を制御します。
        </div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;margin-bottom:6px">
          <button id="aisb-gov-pub-on" type="button" style="font-size:11px;padding:3px 8px">🌐 公開 ON</button>
          <button id="aisb-gov-pub-off" type="button" style="font-size:11px;padding:3px 8px">🔒 非公開 OFF</button>
          <button id="aisb-gov-probe-self" type="button" style="font-size:11px;padding:3px 8px">🔍 自Agent公開URLを検証</button>
        </div>
        <details style="margin-top:4px">
          <summary style="cursor:pointer;color:#1e3a5f;font-weight:600">bridge.yaml 定義 / AgentCard JSON を表示</summary>
          <pre id="aisb-gov-yaml" style="background:#f8fafc;border:1px solid #e2e8f0;padding:6px;border-radius:4px;overflow:auto;font-size:10.5px;margin:4px 0"></pre>
        </details>
      </div>

      <!-- ② 查找・発見 -->
      <div class="aisb-card" style="margin-bottom:8px">
        <b>② 查找・発見 (Discover)</b>
        <div style="color:#555;margin:4px 0">
          ホワイトリスト登録済みの Peer から <code>/.well-known/agent.json</code> をリアルタイム取得します（未登録URLはSSRF防止で拒否）。
        </div>
        <div id="aisb-gov-disc-btns" style="display:flex;gap:4px;flex-wrap:wrap">
          <button class="aisb-gov-disc" data-target="crm" type="button" style="font-size:11px;padding:3px 8px">🔎 CRM Agent を発見</button>
          <button class="aisb-gov-disc" data-target="logistics" type="button" style="font-size:11px;padding:3px 8px">🔎 物流 Agent を発見</button>
          <button class="aisb-gov-disc" data-target="unknown-ext" type="button" style="font-size:11px;padding:3px 8px">⚠️ 未登録外部Agentを探索</button>
        </div>
        <div id="aisb-gov-disc-out" style="margin-top:6px"></div>
      </div>

      <!-- ③ 一覧・相互招待・拒否・遮断 -->
      <div class="aisb-card" style="margin-bottom:8px">
        <div style="display:flex;justify-content:space-between;align-items:center">
          <b>③ 一覧・相互招待・拒否・遮断 (ERP ⇄ CRM / 物流)</b>
          <button id="aisb-gov-refresh" type="button" style="font-size:10.5px;padding:2px 7px">↻ 状態更新</button>
        </div>
        <div style="color:#555;margin:4px 0">
          実システム間で招待を送信します。招待は <a href="/crm/" target="_blank" style="color:#1d4ed8">CRM</a> / <a href="/logistics/" target="_blank" style="color:#1d4ed8">物流</a> の画面にリアルタイムで届き、承認・拒否が即時反映されます。
          差出人は本文ではなく<b>認証済みのキー</b>から相手が判定します。招待中（未承認）・遮断中の相手からの依頼は <b>受信側でも 403</b> です。
          <div id="aisb-gov-ttl" style="color:#92400e;margin-top:2px"></div>
        </div>
        <div id="aisb-gov-peers"></div>
        <div id="aisb-gov-inbox" style="margin-top:8px"></div>
      </div>

      <!-- ④ 認証テスト -->
      <div class="aisb-card" style="margin-bottom:8px">
        <b>④ 認証テスト (Authenticate)</b>
        <div style="color:#555;margin:4px 0">
          相手 Agent の <code>POST /a2a</code> へ実際にリクエストを送り、正規キー・匿名・不正キーの挙動を検証します（LLM消費なし）。
          相手がこちらを遮断/未承認にしていれば、正規キーでも <b>403</b> になります。
        </div>
        <div style="display:flex;gap:4px;flex-wrap:wrap;align-items:center">
          <select id="aisb-gov-auth-peer" style="font-size:11px;padding:2px 4px"><option value="crm">CRM</option><option value="logistics">物流</option></select>
          <button class="aisb-gov-auth" data-mode="valid" type="button" style="font-size:11px;padding:3px 8px">✅ 正規Peerキー</button>
          <button class="aisb-gov-auth" data-mode="anonymous" type="button" style="font-size:11px;padding:3px 8px">🚫 匿名アクセス</button>
          <button class="aisb-gov-auth" data-mode="invalid" type="button" style="font-size:11px;padding:3px 8px">🔑 不正キー</button>
        </div>
        <div id="aisb-gov-auth-out" style="margin-top:6px"></div>
      </div>

      <!-- ⑤ 多段委譲の信頼関係 -->
      <div class="aisb-card" style="margin-bottom:8px">
        <b>⑤ 多段委譲と権限の縮退 (Relay / Attenuation)</b>
        <div style="color:#555;margin:4px 0">
          各 Agent は<b>自分の Peer しか知りません</b>。CRM と物流は直接つながっておらず、CRM の依頼は ERP が中継したときだけ物流に届きます。
          物流は中継された依頼を <code>relay_roles</code> の<b>縮退ロール</b>で評価し（倉庫在庫は見せない）、ループや <code>max_hops</code> 超過は拒否します。
        </div>
        <div id="aisb-gov-topo" style="font-size:11px"></div>
        <div style="color:#555;margin-top:6px">試す: <a href="/crm/" target="_blank" style="color:#1d4ed8">CRM</a> で「🚚 3システム多段」を実行 → <a href="/logistics/" target="_blank" style="color:#1d4ed8">物流の受信ログ</a>に <code>crm → erp → logistics（中継・縮退）</code> と記録されます。</div>
      </div>

      <!-- ⑥ ACL 検証 -->
      <div class="aisb-card" style="margin-bottom:4px">
        <b>⑥ 権限分離の検証 (ACL Probe)</b>
        <div style="color:#555;margin:4px 0">
          ERP の Peer キーで、相手の<b>機密</b>を狙う固定の質問を送ります（質問文は <code>bridge.yaml</code> の <code>acl_probe</code> で固定）。Peer キーは Bridge の外に出しません。
        </div>
        <div style="display:flex;gap:4px;flex-wrap:wrap">
          <button class="aisb-gov-probe" data-peer="crm" type="button" style="font-size:11px;padding:3px 8px">🔒 CRM の違約金(15%)を聞き出す</button>
          <button class="aisb-gov-probe" data-peer="logistics" type="button" style="font-size:11px;padding:3px 8px">🔒 物流の秘密割引(22%)を聞き出す</button>
        </div>
        <div id="aisb-gov-probe-out" style="margin-top:6px"></div>
      </div>
    </div>
  `;

  const $ = (s) => el.querySelector(s);
  let peerInfo = { enabled: false, agent: "", peers: [] };
  let reqSeq = 0;

  function badgeHtml(status) {
    const m = STATUS_META[status] || { label: status, bg: "#f3f4f6", fg: "#555" };
    return `<span style="background:${m.bg};color:${m.fg};padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">${esc(m.label)}</span>`;
  }

  function refLabel(r) {
    return `<span class="aisb-badge">${esc(r.entity)}</span> ${esc(r.title || r.pk)}`;
  }

  function switchSubtab(sub) {
    const isAsk = sub === "ask";
    $("#aisb-a2a-view-ask").style.display = isAsk ? "" : "none";
    $("#aisb-a2a-view-gov").style.display = isAsk ? "none" : "";
    el.querySelectorAll(".aisb-a2a-subtab").forEach((b) => {
      const active = b.dataset.sub === sub;
      b.style.background = active ? "#1e3a5f" : "#f1f5f9";
      b.style.color = active ? "#fff" : "#334155";
      b.style.border = "1px solid " + (active ? "#1e3a5f" : "#cbd5e1");
    });
    if (isAsk) loadPeers();
    else loadGovernance();
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
          const stBadge = badgeHtml(p.status || "active");
          const roleBadge =
            p.status !== "active"
              ? ""
              : p.allowed
                ? `<span style="background:#e6f7ec;color:#0a7d34;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">委譲許可</span>`
                : `<span style="background:#f3f4f6;color:#666;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">方針により委譲不可</span>`;
          return `<div style="margin-top:4px;padding-top:4px;border-top:1px solid #eee">
            <b>Peer: ${esc(peerLabel(p.name))} Agent</b> ${stBadge} ${roleBadge}
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

  async function loadGovernance() {
    const qs = ME ? `?persona=${encodeURIComponent(ME.id)}` : "";
    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/governance${qs}`);
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);

      $("#aisb-gov-pub-badge").innerHTML = d.discoverable
        ? `<span style="background:#e6f7ec;color:#0a7d34;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">公開中 (200)</span>`
        : `<span style="background:#fef2f2;color:#b91c1c;padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">非公開 (404)</span>`;

      $("#aisb-gov-yaml").textContent =
        d.yaml_snippet +
        "\n\n# --- /.well-known/agent.json ---\n" +
        JSON.stringify(d.agent_card, null, 2);

      renderGovPeers(d.peers || []);
      renderGovInbox(d.incoming_invitations || []);
      $("#aisb-gov-ttl").textContent =
        d.governance_expires_in != null
          ? `※ 公開デモの変更は全訪問者で共有されるため、あと約${Math.ceil(d.governance_expires_in / 60)}分で自動的に初期状態へ戻ります。`
          : "";
      loadTopology();
    } catch (e) {
      $("#aisb-gov-peers").innerHTML = `<div style="color:#d03b3b">取得エラー: ${esc(e.message)}</div>`;
    }
  }

  async function loadTopology() {
    const box = $("#aisb-gov-topo");
    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/topology`);
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      const rows = (d.edges || [])
        .map((e) => {
          const path =
            e.kind === "relay"
              ? `${peerLabel(e.from)} → ${peerLabel(e.via)} → ${peerLabel(e.to)}`
              : `${peerLabel(e.from)} → ${peerLabel(e.to)}`;
          const kind =
            e.kind === "relay"
              ? `<span style="color:#92400e;font-weight:700">中継</span>（受信側で縮退）`
              : `<span style="color:#1d4ed8;font-weight:700">委譲</span> 上限: <code>${esc((e.allowed_roles || []).join(", ") || "全ロール")}</code>`;
          return `<tr><td style="padding:2px 4px"><code>${esc(path)}</code></td><td style="padding:2px 4px">${kind}</td><td style="padding:2px 4px">${badgeHtml(e.status === "inactive" ? "blocked" : e.status)}</td></tr>`;
        })
        .join("");
      box.innerHTML = `<table style="width:100%;border-collapse:collapse;margin-top:4px">
        <thead><tr style="color:#64748b;text-align:left"><th style="padding:2px 4px">経路</th><th style="padding:2px 4px">種類</th><th style="padding:2px 4px">状態</th></tr></thead>
        <tbody>${rows}</tbody></table>
        <div style="color:#64748b;margin-top:3px">自Agent: <code>${esc(d.self && d.self.id)}</code> · 受け付ける経路長の上限 <code>max_hops: ${esc(String(d.self && d.self.max_hops))}</code></div>`;
    } catch (e) {
      box.innerHTML = `<span style="color:#d03b3b">取得エラー: ${esc(e.message)}</span>`;
    }
  }

  async function runProbe(peer) {
    const out = $("#aisb-gov-probe-out");
    out.innerHTML = `<div style="color:#666">${esc(peerLabel(peer))} Agent へ検証中（LLMを1回使います）...</div>`;
    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/acl-probe`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ peer }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      const color = d.leaked ? "#b91c1c" : "#0a7d34";
      out.innerHTML = `<div style="padding:6px;border-radius:4px;background:#f8fafc;border-left:3px solid ${color}">
        <div style="color:${color};font-weight:700">${d.leaked ? "漏えいを検出" : "PASS: 機密は返されていません"}</div>
        <div style="font-size:10.5px;color:#555">質問: ${esc(d.question)} · 狙った機密: <code>${esc(d.secret_entity || "")}</code></div>
        <div style="white-space:pre-wrap;margin-top:3px">${esc(d.answer || d.error || "(回答なし)")}</div>
        <div style="font-size:10.5px;color:#666;margin-top:3px">状態 ${esc(d.state)} · 相手側で権限により除外 <b>${esc(String(d.acl_filtered ?? 0))}</b> 件 · 根拠エンティティ: <code>${esc((d.cited_entities || []).join(", ") || "なし")}</code></div>
      </div>`;
    } catch (e) {
      out.innerHTML = `<div style="color:#d03b3b">検証エラー: ${esc(e.message)}</div>`;
    }
  }

  function renderGovInbox(invs) {
    const box = $("#aisb-gov-inbox");
    if (!invs.length) {
      box.innerHTML = `<div style="font-size:10.5px;color:#64748b;border-top:1px dashed #cbd5e1;padding-top:6px">📥 受信した招待（他システムから）: なし（CRM / 物流の画面から招待を送るとここに表示されます）</div>`;
      return;
    }
    const stMap = {
      pending: { label: "承認待ち", bg: "#eff6ff", fg: "#1d4ed8" },
      approved: { label: "承認済", bg: "#e6f7ec", fg: "#0a7d34" },
      rejected: { label: "拒否済", bg: "#fef2f2", fg: "#b91c1c" },
    };
    box.innerHTML = `
      <div style="border-top:1px dashed #cbd5e1;padding-top:6px">
        <div style="font-weight:700;color:#1e3a5f;margin-bottom:4px">📥 受信した招待（実システム間リクエスト）</div>
        ${invs
          .map((inv) => {
            const m = stMap[inv.status] || { label: inv.status, bg: "#f3f4f6", fg: "#555" };
            const badge = `<span style="background:${m.bg};color:${m.fg};padding:1px 6px;border-radius:10px;font-size:10px;font-weight:700">${esc(m.label)}</span>`;
            const actBtns =
              inv.status === "pending"
                ? `<button class="aisb-gov-inv-resp" data-code="${esc(inv.invite_code)}" data-dec="approve" type="button" style="font-size:10.5px;padding:2px 6px">✅ 承認</button>
                   <button class="aisb-gov-inv-resp" data-code="${esc(inv.invite_code)}" data-dec="reject" type="button" style="font-size:10.5px;padding:2px 6px">✖ 拒否</button>`
                : "";
            return `<div style="background:#f8fafc;border:1px solid #e2e8f0;border-radius:4px;padding:5px 6px;margin-top:4px">
              <div style="display:flex;justify-content:space-between;align-items:center;gap:4px">
                <div><b>${esc(inv.from_agent)}</b> ${badge} <span style="font-size:10px;color:#64748b">差出人(キーで判定): <code>${esc(inv.from_peer_name)}</code></span></div>
                <div style="display:flex;gap:4px">${actBtns}</div>
              </div>
              <div style="font-size:10.5px;color:#555;margin-top:2px">コード: <code>${esc(inv.invite_code)}</code> · ${esc(inv.note || "")}</div>
            </div>`;
          })
          .join("")}
      </div>`;

    box.querySelectorAll(".aisb-gov-inv-resp").forEach((btn) => {
      btn.addEventListener("click", async () => {
        btn.disabled = true;
        try {
          const res = await fetch(
            `${ctx.API_BASE}/api/a2a/demo/invitations/${encodeURIComponent(btn.dataset.code)}/respond`,
            {
              method: "POST",
              headers: { "Content-Type": "application/json" },
              body: JSON.stringify({ decision: btn.dataset.dec }),
            },
          );
          if (!res.ok) throw new Error(`HTTP ${res.status}`);
          await loadGovernance();
        } catch (e) {
          alert(`応答失敗: ${e.message}`);
        }
      });
    });
  }

  function renderGovPeers(peers) {
    const box = $("#aisb-gov-peers");
    if (!peers.length) {
      box.innerHTML = `<div style="color:#888">Peer はありません</div>`;
      return;
    }
    box.innerHTML = peers
      .map((p) => {
        const roles = (p.allowed_roles || []).length ? p.allowed_roles.join(", ") : "全ロール";
        const authTxt = p.auth_configured ? "🔑 Peerキー設定済" : "⚠️ キー未設定";
        const invTxt = p.invite_code ? ` · 招待コード: <code>${esc(p.invite_code)}</code>` : "";
        const btns = [];
        if (p.status === "invited") {
          btns.push(`<a href="${esc(PEER_PAGE[p.name] || "/")}" target="_blank" style="font-size:10.5px;padding:2px 6px;border:1px solid #2563eb;border-radius:4px;color:#1d4ed8;text-decoration:none">${esc(peerLabel(p.name))}側で承認 ↗</a>`);
        }
        if (p.status === "active") {
          btns.push(`<button class="aisb-gov-act" data-peer="${esc(p.name)}" data-act="invite" type="button" style="font-size:10.5px;padding:2px 6px">✉️ 招待送信</button>`);
          btns.push(`<button class="aisb-gov-act" data-peer="${esc(p.name)}" data-act="block" type="button" style="font-size:10.5px;padding:2px 6px">🚫 遮断(Block)</button>`);
        }
        if (p.status === "blocked") {
          btns.push(`<button class="aisb-gov-act" data-peer="${esc(p.name)}" data-act="unblock" type="button" style="font-size:10.5px;padding:2px 6px">🔓 遮断解除</button>`);
        }
        if (p.status === "rejected") {
          btns.push(`<button class="aisb-gov-act" data-peer="${esc(p.name)}" data-act="invite" type="button" style="font-size:10.5px;padding:2px 6px">✉️ 再招待送信</button>`);
        }
        return `
          <div style="border-top:1px solid #eee;padding-top:6px;margin-top:6px">
            <div style="display:flex;justify-content:space-between;align-items:center;gap:4px">
              <div><b>${esc(peerLabel(p.name))} Agent</b> ${badgeHtml(p.status)}</div>
              <div style="display:flex;gap:4px">${btns.join("")}</div>
            </div>
            <div style="font-size:10.5px;color:#555;margin-top:2px">
              委譲許可ロール: <code>${esc(roles)}</code> · ${authTxt} · 受信主体: ${p.inbound_bound ? "固定済" : "⚠️未設定"}${(p.relay_to || []).length ? ` · 中継先: <code>${esc(p.relay_to.map(peerLabel).join(", "))}</code>` : ""}${invTxt}
            </div>
          </div>`;
      })
      .join("");

    box.querySelectorAll(".aisb-gov-act").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const peer = btn.dataset.peer;
        const action = btn.dataset.act;
        btn.disabled = true;
        try {
          const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/peers/${encodeURIComponent(peer)}/action`, {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ action }),
          });
          if (!res.ok) {
            const d = await res.json().catch(() => ({}));
            throw new Error(d.detail || `HTTP ${res.status}`);
          }
          await loadGovernance();
        } catch (e) {
          alert(`操作失敗: ${e.message}`);
          btn.disabled = false;
        }
      });
    });
  }

  async function togglePublish(discoverable) {
    const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/publish`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ discoverable }),
    });
    const d = await res.json().catch(() => ({}));
    $("#aisb-gov-disc-out").innerHTML = `<div style="padding:5px;border-radius:4px;background:#f8fafc;border:1px solid #e2e8f0">${esc(d.message || "")}</div>`;
    await loadGovernance();
  }

  async function runDiscover(target) {
    const out = $("#aisb-gov-disc-out");
    out.innerHTML = `<div style="color:#666">AgentCard を探索中...</div>`;
    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/discover`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ target }),
      });
      const d = await res.json().catch(() => ({}));
      const color = d.found ? "#0a7d34" : "#b91c1c";
      const skills = ((d.card && d.card.skills) || []).map((s) => `<code>${esc(s.id || s.name)}</code>`).join(" ");
      const auth = (d.card && d.card.authentication && d.card.authentication.schemes) || [];
      out.innerHTML = `
        <div style="padding:6px;border-radius:4px;background:#f8fafc;border-left:3px solid ${color}">
          <div style="color:${color};font-weight:700">${esc(d.message || "")}</div>
          ${
            d.card
              ? `<div style="margin-top:4px;font-size:10.5px;color:#333">
                  <b>Name</b>: ${esc(d.card.name || "")} (v${esc(d.card.version || "")})<br>
                  <b>Auth</b>: ${esc(auth.join(", ") || "Bearer")}<br>
                  <b>Skills</b>: ${skills || "-"}
                </div>`
              : ""
          }
        </div>`;
    } catch (e) {
      out.innerHTML = `<div style="color:#d03b3b">探索エラー: ${esc(e.message)}</div>`;
    }
  }

  async function runVerifyAuth(mode) {
    const out = $("#aisb-gov-auth-out");
    const authPeer = $("#aisb-gov-auth-peer").value;
    out.innerHTML = `<div style="color:#666">${esc(peerLabel(authPeer))} Agent (/a2a) へ認証テスト送信中...</div>`;
    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/verify-auth`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ peer: authPeer, mode }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(d.detail || `HTTP ${res.status}`);
      const color = d.authenticated ? "#0a7d34" : "#b91c1c";
      out.innerHTML = `
        <div style="padding:6px;border-radius:4px;background:#f8fafc;border-left:3px solid ${color}">
          <div style="color:${color};font-weight:700">${esc(d.summary || "")}</div>
          <div style="font-size:10.5px;color:#444;margin-top:3px">
            送信ヘッダ: <code>${esc(d.header_sent || "")}</code><br>
            HTTP Status: <b>${esc(String(d.http_status))}</b>
          </div>
        </div>`;
    } catch (e) {
      out.innerHTML = `<div style="color:#d03b3b">認証テスト失敗: ${esc(e.message)}</div>`;
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
    const peerNames = (peerInfo.peers || []).map((p) => peerLabel(p.name)).join(" / ") || "Peer";
    const synthesize = $("#aisb-a2a-synth").checked;
    out.innerHTML = `<div class="aisb-card"><b>A2A 連携回答を実行中...</b>
      <div style="color:#666;font-size:11.5px;margin-top:4px">① 自システム(${esc(peerInfo.agent || "ERP")})の権限検索と、② ${esc(peerNames)} Agent への A2A 質問委譲を並列実行しています...</div></div>`;

    try {
      const res = await fetch(`${ctx.API_BASE}/api/a2a/demo/federated-ask`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ persona: ME.id, question: q, synthesize }),
      });
      const d = await res.json().catch(() => ({}));
      if (!res.ok) throw new Error(`${res.status} ${d.detail || ""}`.trim());
      if (seq !== reqSeq) return;

      const loc = d.local || {};
      const KIND = { local: "自システム検索", delegate: "A2A 委譲", relay: "中継", synthesize: "統合回答" };
      const traceRows = (d.trace || [])
        .map((t) => {
          const ok = t.status === "completed";
          const st = ok ? `<span style="color:#0a7d34">✔ ${esc(t.status)}</span>` : `<span style="color:#b91c1c">✖ ${esc(t.status)}</span>`;
          const extra = [
            t.acl_filtered != null ? `除外 ${esc(String(t.acl_filtered))}` : "",
            t.attenuated ? `縮退 <code>${esc((t.effective_roles || []).join(","))}</code>` : "",
            t.error ? esc(t.error) : "",
          ].filter(Boolean).join(" · ");
          return `<tr>
            <td style="padding:2px 4px;color:#64748b">${esc(String(t.step))}</td>
            <td style="padding:2px 4px">${esc(KIND[t.kind] || t.kind)}</td>
            <td style="padding:2px 4px"><code>${esc((t.path || []).map(peerLabel).join(" → "))}</code></td>
            <td style="padding:2px 4px">${st}</td>
            <td style="padding:2px 4px;text-align:right">${t.latency_ms != null ? esc(String(t.latency_ms)) + "ms" : "-"}</td>
            <td style="padding:2px 4px;color:#555">${extra}</td></tr>`;
        })
        .join("");
      const traceHtml = traceRows
        ? `<div class="aisb-card" style="font-size:11px">
            <b>🧭 実行トレース</b> <span style="color:#666">（各ホップは相手側で独立に権限判定・監査されます）</span>
            <table style="width:100%;border-collapse:collapse;margin-top:4px"><tbody>${traceRows}</tbody></table>
          </div>`
        : "";
      const synthHtml = d.synthesis
        ? `<div class="aisb-card" style="border-left:3px solid #7c3aed;background:#faf5ff">
            <div><b>🧩 統合回答</b> <span style="color:#666;font-size:11px">（各Agentの結論だけから作成 · ${esc(String(d.synthesis.latency_ms))}ms）</span></div>
            <div style="white-space:pre-wrap;font-size:12px;margin-top:6px">${esc(d.synthesis.answer || "(回答なし)")}</div>
            <div style="font-size:10.5px;color:#666;margin-top:4px">※ 相手システムの DB には一切アクセスしていません。[erp] [crm] [logistics] は根拠の Agent です。</div>
          </div>`
        : "";
      const cites = (loc.citations || []).map((c) => `<li>[${esc(String(c.n))}] ${refLabel(c)}</li>`).join("");

      let html = synthHtml + traceHtml + `
        <div class="aisb-card" style="border-left:3px solid #2563eb">
          <div><b>① ${esc(d.agent || "自システム (ERP)")}</b> <span style="color:#666;font-size:11px">(${esc(ME.label)}の権限で回答)</span></div>
          <div style="white-space:pre-wrap;font-size:12px;margin:6px 0">${esc(loc.answer || "(回答なし)")}</div>
          <div style="font-size:11px;color:#666">権限で除外: <b>${esc(String(loc.acl_filtered ?? 0))}</b> 件 · 監査ID: <code>${esc(String(loc.audit_id || "").slice(0, 8))}</code></div>
          ${cites ? `<ul style="margin:4px 0 0 16px;padding:0;font-size:11px">${cites}</ul>` : ""}
        </div>`;

      html += (d.peers || [])
        .map((p) => {
          const head = `<b>② ${esc(peerLabel(p.peer))} Agent</b> <span class="aisb-badge">A2A</span>`;
          if (p.status === "blocked") {
            return `<div class="aisb-card" style="border-left:3px solid #374151">
              <div>${head} ${badgeHtml("blocked")}</div>
              <div style="font-size:12px;color:#555;margin-top:4px">管理画面で <b>遮断 (Block)</b> されているため、相手システムへの通信を完全に停止しました。「発見・認証・管理」タブから遮断解除できます。</div>
            </div>`;
          }
          if (p.status === "invited" || p.status === "rejected") {
            return `<div class="aisb-card" style="border-left:3px solid #b91c1c">
              <div>${head} ${badgeHtml(p.status)}</div>
              <div style="font-size:12px;color:#555;margin-top:4px">ステータスが <b>${esc(p.status)}</b>（未承認）のため委譲していません。承認後に連携可能になります。</div>
            </div>`;
          }
          if (p.status === "forbidden") {
            return `<div class="aisb-card" style="border-left:3px solid #9ca3af">
              <div>${head} <span style="font-size:11px;color:#666">委譲ブロック</span></div>
              <div style="font-size:12px;color:#555;margin-top:4px">${esc(ME.label)}ロールは ${esc(peerLabel(p.peer))} への委譲が許可されていないため、相手システムには問い合わせていません（<code>bridge.yaml</code> の <code>allowed_roles</code> で制御）。</div>
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

  // Event bindings
  el.querySelectorAll(".aisb-a2a-subtab").forEach((b) =>
    b.addEventListener("click", () => switchSubtab(b.dataset.sub)),
  );
  $("#aisb-a2a-run").addEventListener("click", runA2A);
  $("#aisb-a2a-q").addEventListener("keydown", (e) => e.key === "Enter" && runA2A());
  el.querySelectorAll(".aisb-a2a-chip").forEach((btn) => {
    btn.addEventListener("click", () => {
      const s = SCENARIOS[Number(btn.dataset.idx)];
      if (!s) return;
      $("#aisb-a2a-q").value = s.q;
      $("#aisb-a2a-synth").checked = !!s.synthesize;
      runA2A();
    });
  });

  $("#aisb-gov-pub-on").addEventListener("click", () => togglePublish(true));
  $("#aisb-gov-pub-off").addEventListener("click", () => togglePublish(false));
  $("#aisb-gov-probe-self").addEventListener("click", () => runDiscover("self"));
  el.querySelectorAll(".aisb-gov-disc").forEach((b) =>
    b.addEventListener("click", () => runDiscover(b.dataset.target)),
  );
  el.querySelectorAll(".aisb-gov-probe").forEach((b) =>
    b.addEventListener("click", () => runProbe(b.dataset.peer)),
  );
  el.querySelectorAll(".aisb-gov-auth").forEach((b) =>
    b.addEventListener("click", () => runVerifyAuth(b.dataset.mode)),
  );
  $("#aisb-gov-refresh").addEventListener("click", () => loadGovernance());
  $("#aisb-gov-reset").addEventListener("click", async () => {
    await fetch(`${ctx.API_BASE}/api/a2a/demo/reset`, { method: "POST" });
    $("#aisb-gov-disc-out").innerHTML = "";
    $("#aisb-gov-auth-out").innerHTML = "";
    await loadGovernance();
  });

  switchSubtab("ask");
};
