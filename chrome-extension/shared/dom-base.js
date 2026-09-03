// shared/dom-base.js
// Shadow DOM/HTMLエスケープ等、DOM生成にまつわる純粋なユーティリティ。
window.AISB = window.AISB || {};

window.AISB.domBase = (function () {
  // content/sidebar.css のインライン複製。
  // 理由: chrome.runtime.getURL()+fetch() によるランタイム読み込みは
  // 拡張コンテキスト無効化のタイミング次第で "chrome-extension://invalid/"
  // エラーを起こし、CSSが適用されないことがあった。ビルドプロセスを持たない
  // この拡張では、ファイルを分けたままJS文字列としてインライン化するのが
  // 最も単純で確実な回避策。content/sidebar.css を編集したら、必ずこの定数にも
  // 同じ内容を反映すること(以前は content/content.js 内で複製していたが、
  // モジュール分割に伴いここに移動した)。
  const CSS = `
/* Shadow DOM 内スタイル。ホストページに一切影響を与えない */
:host, #aisb-root {
  all: initial;
  /* ---- カラートークン (2026-08-20 配色刷新) ----
     基準はカテゴリカル配色(色覚多様性を考慮したhue順)。タブは19枚あるが、
     色は「唯一の識別子」ではなくラベルテキストを補助する第二の手がかりとして使う
     (色だけに依存しない = 常にラベル文字が併記される)ため、8スロットの理論上限を
     超えて7系統(赤はステータス専用として温存し使わない)に機能グルーピングして
     割り当てている。 */
  --aisb-ink: #16181d;
  --aisb-ink-soft: #4b5058;
  --aisb-muted: #82888f;
  --aisb-page: #f3f5f9;
  --aisb-surface: #ffffff;
  --aisb-border: #dfe3ea;
  --aisb-border-soft: #eceff3;

  --aisb-blue: #2a78d6;
  --aisb-blue-deep: #17497e;
  --aisb-blue-tint: #eaf2fd;

  --aisb-orange: #eb6834;
  --aisb-orange-deep: #a8461d;
  --aisb-orange-tint: #fdeee6;

  --aisb-aqua: #1baf7a;
  --aisb-aqua-deep: #0d7a52;
  --aisb-aqua-tint: #e4f7f0;

  --aisb-yellow: #eda100;
  --aisb-yellow-deep: #8a5c00;
  --aisb-yellow-tint: #fdf1de;

  --aisb-magenta: #e87ba4;
  --aisb-magenta-deep: #a13d68;
  --aisb-magenta-tint: #fbe9f0;

  --aisb-green: #1a8a1a;
  --aisb-green-deep: #0a5c0a;
  --aisb-green-tint: #e6f7e6;

  --aisb-violet: #6a4fc9;
  --aisb-violet-deep: #4a3aa7;
  --aisb-violet-tint: #f0edfc;

  --aisb-good: #0ca30c;
  --aisb-warning: #b8790a;
  --aisb-critical: #d03b3b;
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
  background: linear-gradient(135deg, var(--aisb-blue), var(--aisb-violet-deep));
  color: #fff;
  width: 38px;
  height: 38px;
  border-radius: 50% 0 0 50%;
  display: flex;
  align-items: center;
  justify-content: center;
  cursor: pointer;
  font-size: 18px;
  z-index: 2147483647;
  box-shadow: -2px 0 8px rgba(20,30,50,0.35);
}
#aisb-panel {
  position: fixed;
  top: 0;
  right: 0;
  width: var(--aisb-width, 380px);
  height: 100vh;
  background: var(--aisb-surface);
  box-shadow: -6px 0 20px rgba(15,23,42,0.22);
  border-radius: 10px 0 0 10px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
  z-index: 2147483646;
  transition: transform 0.2s ease;
}
.aisb-collapsed #aisb-panel {
  transform: translateX(100%);
}
#aisb-header {
  background: linear-gradient(135deg, #142c4d 0%, #1c3f61 45%, #3a2f7a 100%);
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
  flex-wrap: wrap;
  gap: 3px;
  border-bottom: 1px solid var(--aisb-border);
  background: var(--aisb-page);
  padding: 6px 6px 0;
}
.aisb-tab {
  --tab-c: var(--aisb-blue);
  --tab-c-deep: var(--aisb-blue-deep);
  --tab-c-tint: var(--aisb-blue-tint);
  flex: 0 0 auto;
  display: inline-flex;
  align-items: center;
  padding: 7px 10px 6px;
  border: none;
  border-radius: 6px 6px 0 0;
  background: transparent;
  cursor: pointer;
  font-size: 11px;
  font-weight: 500;
  color: var(--aisb-ink-soft);
  border-bottom: 3px solid transparent;
  white-space: nowrap;
  transition: background 0.12s ease, color 0.12s ease;
}
.aisb-tab::before {
  content: "";
  display: inline-block;
  width: 6px;
  height: 6px;
  flex: 0 0 auto;
  border-radius: 50%;
  background: var(--tab-c);
  margin-right: 5px;
}
.aisb-tab:hover {
  background: var(--aisb-surface);
  color: var(--aisb-ink);
}
.aisb-tab.active {
  background: var(--tab-c-tint);
  color: var(--tab-c-deep);
  border-bottom-color: var(--tab-c);
  font-weight: 700;
}

/* ---- タブの機能グルーピング配色 (7系統、赤はステータス専用のため不使用) ---- */
.aisb-tab[data-panel="chat"],
.aisb-tab[data-panel="assistant"],
.aisb-tab[data-panel="convinput"] {
  --tab-c: var(--aisb-blue);
  --tab-c-deep: var(--aisb-blue-deep);
  --tab-c-tint: var(--aisb-blue-tint);
}
.aisb-tab[data-panel="nlsql"],
.aisb-tab[data-panel="search"],
.aisb-tab[data-panel="analytics"],
.aisb-tab[data-panel="recommend"] {
  --tab-c: var(--aisb-aqua);
  --tab-c-deep: var(--aisb-aqua-deep);
  --tab-c-tint: var(--aisb-aqua-tint);
}
.aisb-tab[data-panel="inventory"],
.aisb-tab[data-panel="purchase"] {
  --tab-c: var(--aisb-orange);
  --tab-c-deep: var(--aisb-orange-deep);
  --tab-c-tint: var(--aisb-orange-tint);
}
.aisb-tab[data-panel="profit"],
.aisb-tab[data-panel="arap"] {
  --tab-c: var(--aisb-green);
  --tab-c-deep: var(--aisb-green-deep);
  --tab-c-tint: var(--aisb-green-tint);
}
.aisb-tab[data-panel="alerts"],
.aisb-tab[data-panel="workflows"],
.aisb-tab[data-panel="notifications"] {
  --tab-c: var(--aisb-yellow);
  --tab-c-deep: var(--aisb-yellow-deep);
  --tab-c-tint: var(--aisb-yellow-tint);
}
.aisb-tab[data-panel="ocr"],
.aisb-tab[data-panel="websearch"] {
  --tab-c: var(--aisb-magenta);
  --tab-c-deep: var(--aisb-magenta-deep);
  --tab-c-tint: var(--aisb-magenta-tint);
}
.aisb-tab[data-panel="legacy"],
.aisb-tab[data-panel="customers"],
.aisb-tab[data-panel="admin"] {
  --tab-c: var(--aisb-violet);
  --tab-c-deep: var(--aisb-violet-deep);
  --tab-c-tint: var(--aisb-violet-tint);
}

#aisb-body {
  flex: 1;
  overflow-y: auto;
  padding: 14px;
  font-size: 13px;
  color: var(--aisb-ink);
  background: var(--aisb-page);
  line-height: 1.55;
}
.aisb-card {
  background: var(--aisb-surface);
  border: 1px solid var(--aisb-border);
  border-radius: 8px;
  padding: 9px 11px;
  margin-bottom: 9px;
  font-size: 12px;
  line-height: 1.6;
  box-shadow: 0 1px 2px rgba(16,24,40,0.05);
}
.aisb-badge {
  display: inline-block;
  background: var(--aisb-blue-tint);
  color: var(--aisb-blue-deep);
  border-radius: 4px;
  padding: 2px 8px;
  font-size: 11px;
  font-weight: 600;
  margin-bottom: 8px;
}
.aisb-ws-source {
  font-size: 11px;
  font-weight: 600;
  border-radius: 6px;
  padding: 5px 9px;
  margin: 0 0 8px 0;
}
.aisb-ws-source-real {
  background: var(--aisb-green-tint);
  color: var(--aisb-green-deep);
}
.aisb-ws-source-mock {
  background: var(--aisb-yellow-tint);
  color: var(--aisb-yellow-deep);
}
.aisb-insight-card {
  background: var(--aisb-violet-tint);
  border: 1px solid #d6cdf2;
  border-left: 4px solid var(--aisb-violet);
  white-space: pre-wrap;
}
/* ルールベースの集計コメント(summary)用。本物のAI解釈(aisb-insight-card、紫)とは
   意図的に見た目を分け、「これはAIの判断ではない」ことを一目で区別できるようにする。
   (aisb_embed/static/sidebar.css の移植版。編集したら content/sidebar.css にも反映すること) */
.aisb-summary-card {
  background: #f1f2f4;
  border: 1px solid #d9dce1;
  border-left: 4px solid #8a929e;
  white-space: pre-wrap;
}
#aisb-chat-log {
  height: calc(100vh - 220px);
  overflow-y: auto;
  margin-bottom: 8px;
}
.aisb-msg {
  margin-bottom: 8px;
  padding: 7px 11px;
  border-radius: 10px;
  max-width: 90%;
  font-size: 12px;
  line-height: 1.55;
}
.aisb-msg-user {
  background: var(--aisb-blue);
  color: #fff;
  margin-left: auto;
}
.aisb-msg-assistant {
  background: var(--aisb-surface);
  border: 1px solid var(--aisb-border);
  color: var(--aisb-ink);
}
#aisb-chat-input-row, #aisb-search-row {
  display: flex;
  gap: 6px;
}
#aisb-chat-input, #aisb-search-input {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid var(--aisb-border);
  border-radius: 4px;
  font-size: 12px;
  background: var(--aisb-surface);
}
#aisb-chat-send, #aisb-search-run, #aisb-ocr-run {
  background: var(--aisb-blue);
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}
#aisb-chat-send:hover, #aisb-search-run:hover, #aisb-ocr-run:hover {
  background: var(--aisb-blue-deep);
}
#aisb-ocr-result {
  background: var(--aisb-surface);
  border: 1px solid var(--aisb-border);
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
  border-bottom: 1px solid var(--aisb-border);
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
  background: var(--aisb-blue);
}
.aisb-bar.aisb-bar-forecast {
  background: repeating-linear-gradient(45deg, #9ec5f4, #9ec5f4 4px, #cde2fb 4px, #cde2fb 8px);
}
.aisb-bar-label {
  font-size: 9px;
  color: var(--aisb-muted);
  writing-mode: vertical-rl;
  text-orientation: mixed;
}
.aisb-legend {
  display: flex;
  gap: 12px;
  font-size: 11px;
  color: var(--aisb-ink-soft);
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

/* ---- 再受注リスク / ワークフロー (ステータス配色は固定・カテゴリ配色と混同しない) ---- */
.aisb-risk-overdue { border-left: 4px solid var(--aisb-critical); }
.aisb-risk-due_soon { border-left: 4px solid var(--aisb-warning); }
.aisb-risk-on_track { border-left: 4px solid var(--aisb-good); }
.aisb-risk-tag {
  display: inline-block;
  font-size: 10px;
  font-weight: 700;
  padding: 1px 6px;
  border-radius: 3px;
  margin-left: 6px;
}
.aisb-risk-overdue .aisb-risk-tag { background: #fdecea; color: var(--aisb-critical); }
.aisb-risk-due_soon .aisb-risk-tag { background: var(--aisb-yellow-tint); color: var(--aisb-warning); }
.aisb-risk-on_track .aisb-risk-tag { background: var(--aisb-green-tint); color: var(--aisb-good); }

.aisb-section-title {
  font-size: 12px;
  font-weight: 700;
  color: var(--aisb-ink);
  margin: 10px 0 6px;
}
.aisb-btn-row {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
  flex-wrap: wrap;
}
.aisb-btn-row button {
  background: var(--aisb-blue);
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 6px 10px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
}
.aisb-btn-row button:hover {
  background: var(--aisb-blue-deep);
}
.aisb-btn-row button.aisb-btn-secondary {
  background: var(--aisb-surface);
  color: var(--aisb-blue-deep);
  border: 1px solid var(--aisb-border);
}
.aisb-btn-row button.aisb-btn-secondary:hover {
  background: var(--aisb-blue-tint);
}
.aisb-event-card {
  background: var(--aisb-yellow-tint);
  border: 1px solid #f0dca0;
  border-radius: 6px;
  padding: 6px 8px;
  margin-bottom: 6px;
  font-size: 11px;
}
.aisb-event-time {
  color: var(--aisb-muted);
  font-size: 10px;
  display: block;
  margin-top: 2px;
}

/* ---- 通知 / 管理 (Phase4) ---- */
.aisb-notif-unread {
  box-shadow: inset 3px 0 0 var(--aisb-blue);
  background: var(--aisb-blue-tint);
}
.aisb-notif-read-btn {
  margin-top: 6px;
  background: var(--aisb-blue);
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 3px 8px;
  cursor: pointer;
  font-size: 10px;
}
.aisb-notif-read-btn:hover {
  background: var(--aisb-blue-deep);
}

/* ---- 業務データ(レガシーERP全13エンティティ) パネル ---- */
.aisb-inline-row {
  display: flex;
  gap: 6px;
  margin-bottom: 8px;
}
.aisb-inline-row select {
  padding: 6px 8px;
  border: 1px solid var(--aisb-border);
  border-radius: 4px;
  font-size: 12px;
  background: var(--aisb-surface);
}
.aisb-inline-row input[type="text"],
.aisb-inline-row input[type="number"] {
  flex: 1;
  padding: 6px 8px;
  border: 1px solid var(--aisb-border);
  border-radius: 4px;
  font-size: 12px;
}
.aisb-inline-row button {
  background: var(--aisb-blue);
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 6px 12px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}
.aisb-inline-row button:hover {
  background: var(--aisb-blue-deep);
}
.aisb-context-banner {
  background: var(--aisb-blue-tint);
  border: 1px solid #b9d3ec;
  border-radius: 6px;
  padding: 8px 10px;
  margin-bottom: 10px;
  font-size: 12px;
  line-height: 1.6;
}
.aisb-context-banner .aisb-summarize-btn {
  margin-top: 6px;
  background: var(--aisb-blue-deep);
  color: #fff;
  border: none;
  border-radius: 4px;
  padding: 5px 10px;
  cursor: pointer;
  font-size: 11px;
}
.aisb-table {
  width: 100%;
  border-collapse: collapse;
  font-size: 11px;
}
.aisb-table th, .aisb-table td {
  border-bottom: 1px solid var(--aisb-border-soft);
  padding: 5px 6px;
  text-align: left;
  vertical-align: top;
}
.aisb-table th {
  color: var(--aisb-ink-soft);
  font-weight: 700;
  background: var(--aisb-page);
  border-bottom: 2px solid var(--aisb-border);
  position: sticky;
  top: 0;
}
.aisb-table tr:nth-child(even) td {
  background: #fafbfd;
}
.aisb-table tr:hover td {
  background: var(--aisb-blue-tint);
}
.aisb-link-btn {
  background: transparent;
  border: none;
  color: var(--aisb-blue-deep);
  cursor: pointer;
  font-size: 11px;
  padding: 0;
  text-decoration: underline;
  font-weight: 600;
}

/* ---- リサイズハンドル / 最小化・最大化 (サイドバーUI改善) ---- */
#aisb-resize-handle {
  position: absolute;
  left: -4px;
  top: 0;
  bottom: 0;
  width: 8px;
  cursor: ew-resize;
  z-index: 20;
  background: transparent;
}
#aisb-resize-handle:hover,
#aisb-resize-handle.aisb-resizing {
  background: rgba(42, 120, 214, 0.35);
}
#aisb-header-btns {
  display: flex;
  align-items: center;
  gap: 2px;
}
#aisb-header-btns button {
  font-size: 14px;
  line-height: 1;
  padding: 4px 6px;
  border-radius: 3px;
}
#aisb-header-btns button:hover {
  background: rgba(255, 255, 255, 0.18);
}
.aisb-maximized #aisb-panel {
  width: min(920px, 92vw) !important;
}
.aisb-maximized #aisb-resize-handle {
  cursor: default;
  pointer-events: none;
}
.aisb-minimized #aisb-tabs,
.aisb-minimized #aisb-body,
.aisb-minimized #aisb-resize-handle {
  display: none;
}
.aisb-minimized #aisb-panel {
  height: auto;
}
/* パネル切替時も前回の表示内容を保持するため、非表示パネルは display:none のみで
   DOM/JS状態(スクロール位置・入力値・取得済みデータ)を破棄しない */
.aisb-panel-pane {
  min-height: 40px;
}

/* ---- AI検索(自然言語→構造化フィルタ, 5.4.11差分実装) パネル ---- */
.aisb-chip-row {
  display: flex;
  flex-wrap: wrap;
  gap: 6px;
  margin-bottom: 8px;
}
.aisb-chip {
  background: var(--aisb-aqua-tint);
  color: var(--aisb-aqua-deep);
  border: 1px solid #a7e3cd;
  border-radius: 999px;
  padding: 4px 10px;
  cursor: pointer;
  font-size: 11px;
  font-weight: 600;
  line-height: 1.4;
  max-width: 100%;
  white-space: normal;
  text-align: left;
}
.aisb-chip:hover {
  background: #cdeee0;
}
.aisb-chip:active {
  background: #b7e5d3;
}
#aisb-nlsql-q {
  width: 100%;
  min-height: 56px;
  padding: 6px 8px;
  border: 1px solid var(--aisb-border);
  border-radius: 4px;
  font-size: 12px;
  font-family: inherit;
  resize: vertical;
  margin-bottom: 6px;
}
.aisb-filter-summary {
  background: var(--aisb-page);
  border: 1px solid var(--aisb-border);
  border-radius: 6px;
  padding: 6px 8px;
  margin-bottom: 8px;
  font-size: 11px;
  color: var(--aisb-ink-soft);
  font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
  white-space: pre-wrap;
  word-break: break-all;
}
.aisb-hint {
  font-size: 11px;
  color: var(--aisb-muted);
  line-height: 1.5;
  margin-bottom: 6px;
}
/* AIが実際に生成・実行したSQLは存在しない(実SQLエンジン不在、AIは構造化フィルタ/
   specのみ生成)ため、検証済み条件から機械的に組み立てた疑似SQL(表示専用、実行
   しない)を、実行結果と見分けやすいよう .aisb-filter-summary とは別のコード風
   (ダーク背景)スタイルで見せる。 */
.aisb-sql-preview {
  background: #182335;
  color: #d7e3f5;
  border: 1px solid #2c3c56;
  border-radius: 6px;
  padding: 6px 8px;
  margin: 0 0 8px;
  font-size: 11px;
  font-family: ui-monospace, "SFMono-Regular", Menlo, monospace;
  white-space: pre-wrap;
  word-break: break-all;
  overflow-x: auto;
}
.aisb-sql-preview code {
  font-family: inherit;
  background: none;
}
.aisb-warning-card {
  background: var(--aisb-yellow-tint);
  border: 1px solid #f0dca0;
  border-left: 3px solid var(--aisb-warning);
  color: #6b4a08;
  font-size: 11px;
}

/* ---- クロス分析(与信リスク/在庫逼迫/滞留債権) 横棒ランキングチャート ---- */
.aisb-hbar-chart {
  display: block;
  height: auto;
  align-items: normal;
  padding: 4px 0 0;
  border-bottom: none;
}
.aisb-hbar-row {
  display: flex;
  align-items: center;
  gap: 6px;
  margin-bottom: 6px;
}
.aisb-hbar-label {
  width: 92px;
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--aisb-ink-soft);
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.aisb-hbar-track {
  flex: 1;
  height: 10px;
  background: var(--aisb-border-soft);
  border-radius: 5px;
  overflow: hidden;
}
.aisb-hbar-fill {
  height: 100%;
  background: var(--aisb-blue);
  border-radius: 5px;
}
.aisb-hbar-track.aisb-hbar-warn .aisb-hbar-fill { background: var(--aisb-warning); }
.aisb-hbar-track.aisb-hbar-over .aisb-hbar-fill { background: var(--aisb-critical); }
.aisb-hbar-value {
  width: 118px;
  flex: 0 0 auto;
  font-size: 10px;
  color: var(--aisb-ink-soft);
  text-align: right;
  white-space: nowrap;
}

/* ---- 時系列トレンド(折れ線, AIレポート自動生成でgroup_byが日付の場合) ---- */
.aisb-trend-svg {
  width: 100%;
  height: 100px;
  display: block;
}
.aisb-trend-axis {
  stroke: var(--aisb-border);
  stroke-width: 1;
}
.aisb-trend-area {
  fill: rgba(42, 120, 214, 0.12);
  stroke: none;
}
.aisb-trend-line {
  fill: none;
  stroke: var(--aisb-blue);
  stroke-width: 2;
  stroke-linejoin: round;
  stroke-linecap: round;
}
.aisb-trend-dot {
  fill: var(--aisb-blue);
  stroke: #fff;
  stroke-width: 2;
}
.aisb-trend-endlabel {
  font-size: 9px;
  fill: var(--aisb-blue-deep);
  font-weight: 700;
}
.aisb-trend-xlabels {
  display: flex;
  justify-content: space-between;
  font-size: 10px;
  color: var(--aisb-muted);
  margin: 2px 0 6px;
}

/* ---- 状態分類の構成比(part-to-whole, 積み上げ横棒1本+凡例) ---- */
.aisb-dist-bar {
  display: flex;
  height: 16px;
  border-radius: 8px;
  overflow: hidden;
  background: var(--aisb-border-soft);
  margin-bottom: 6px;
}
.aisb-dist-seg {
  height: 100%;
  border-right: 2px solid #fff;
}
.aisb-dist-seg:last-child {
  border-right: none;
}
.aisb-dist-legend {
  display: flex;
  flex-wrap: wrap;
  gap: 10px;
  font-size: 11px;
  color: var(--aisb-ink-soft);
  margin-bottom: 10px;
}
.aisb-dist-legend-item {
  display: flex;
  align-items: center;
  white-space: nowrap;
}

/* ---- AI検索パネルのサブタブ(定型レポート/AIレポート生成/自然文検索を切替) ---- */
.aisb-subtabs {
  display: flex;
  gap: 4px;
  margin-bottom: 10px;
  border-bottom: 1px solid var(--aisb-border);
}
.aisb-subtab {
  flex: 1;
  padding: 7px 4px;
  border: none;
  background: transparent;
  cursor: pointer;
  font-size: 11px;
  color: var(--aisb-ink-soft);
  border-bottom: 2px solid transparent;
}
.aisb-subtab.active {
  color: var(--aisb-blue-deep);
  border-bottom-color: var(--aisb-blue);
  font-weight: 700;
}
.aisb-subpanel {
  display: none;
}
.aisb-subpanel.active {
  display: block;
}
`;

  function escapeHtml(v) {
    return String(v ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  }

  // 今開いているレガシー画面のURL (例: /Order/Detail/ORD1003, /Customer/List) から
  // エンティティ・画面種別・IDを読み取る。マッチしなければ null (ダッシュボード等)。
  // legacyEntities は shared/config-base.js の LEGACY_ENTITIES を呼び出し側から渡す
  // (dom-base はドメイン知識を持たない純粋なDOM/文字列ユーティリティに留める方針)。
  function detectLegacyContext(legacyEntities) {
    const m = location.pathname.match(/^\/([A-Za-z]+)\/(List|Entry|Detail|Search|Inquiry|Register)(?:\/([^/]+))?/);
    if (!m) return null;
    const [, entity, action, id] = m;
    if (!legacyEntities.some((e) => e.id === entity)) return null;
    return { entity, action, id: id || null };
  }

  // クロス分析(与信リスク/在庫逼迫/滞留債権)・AIレポート自動生成 向けのチャート描画。
  // Chart.js等は使わず既存のCSSバーチャート方針(analytics参照)を踏襲するが、狭い
  // サイドバー幅では縦棒より横棒の方がラベル(顧客名/商品名)を読みやすいため、
  // ai-api-server側が返す chart(type/unit/categories/series) 形式を type ごとに
  // 描画し分ける入口として renderChart() にまとめている(旧名renderRankedBarChartから
  // 改名: 棒グラフ専用ではなくなったため)。
  //   type=ranked-bar-grouped : 「限度額に対する使用量」のようなゲージ表現
  //                             (series[0]=上限, series[1]=実績)
  //   type=trend-line         : group_byが日付(YYYY-MM-DD)の場合の時系列トレンド
  //                             (dynamic_analysis_service.pyが機械的に判定、AI非依存)
  //   type=ranked-bar (既定)   : 単一指標のランキング表現
  function renderChart(chart) {
    if (chart && chart.type === "trend-line") return renderTrendLineChart(chart);
    return renderRankedBarChart(chart);
  }

  function renderRankedBarChart(chart) {
    const categories = chart?.categories || [];
    if (!categories.length) return "<p>該当データがありません</p>";
    const unit = chart.unit || "";

    if (chart.type === "ranked-bar-grouped" && (chart.series || []).length >= 2) {
      const limits = chart.series[0].values;
      const actuals = chart.series[1].values;
      const legend =
        `<div class="aisb-legend">` +
        `<span><span class="aisb-legend-dot" style="background:#9ec5f4"></span>${escapeHtml(chart.series[0].label)}</span>` +
        `<span><span class="aisb-legend-dot" style="background:#2a78d6"></span>${escapeHtml(chart.series[1].label)}</span>` +
        `</div>`;
      const rows = categories
        .map((cat, i) => {
          const limit = Number(limits[i]) || 0;
          const actual = Number(actuals[i]) || 0;
          const ratio = limit > 0 ? actual / limit : 0;
          const pct = Math.max(2, Math.min(100, Math.round(ratio * 100)));
          const stateClass = ratio >= 1 ? "aisb-hbar-over" : ratio >= 0.8 ? "aisb-hbar-warn" : "";
          return `<div class="aisb-hbar-row">
            <div class="aisb-hbar-label" title="${escapeHtml(cat)}">${escapeHtml(cat)}</div>
            <div class="aisb-hbar-track ${stateClass}"><div class="aisb-hbar-fill" style="width:${pct}%"></div></div>
            <div class="aisb-hbar-value">${Math.round(actual).toLocaleString()} / ${Math.round(limit).toLocaleString()}${unit}</div>
          </div>`;
        })
        .join("");
      return legend + rows;
    }

    const values = (chart.series && chart.series[0] && chart.series[0].values) || [];
    const max = Math.max(...values.map((v) => Math.abs(Number(v) || 0)), 1);
    return categories
      .map((cat, i) => {
        const v = values[i];
        const pct = v == null ? 0 : Math.max(2, Math.min(100, Math.round((Math.abs(Number(v)) / max) * 100)));
        const display = v == null ? "-" : `${Math.round(Number(v)).toLocaleString()}${unit}`;
        return `<div class="aisb-hbar-row">
          <div class="aisb-hbar-label" title="${escapeHtml(cat)}">${escapeHtml(cat)}</div>
          <div class="aisb-hbar-track"><div class="aisb-hbar-fill" style="width:${pct}%"></div></div>
          <div class="aisb-hbar-value">${display}</div>
        </div>`;
      })
      .join("");
  }

  // 時系列トレンド(折れ線)。純SVGで描画(ライブラリ不使用の既定方針を踏襲)。
  // 直近値のみ数値を直接ラベル表示し(全点ラベルは読みづらいため)、両端の
  // カテゴリ(日付)はX軸ラベルとして下に添える。単一系列のみ対応(凡例は
  // 系列名がタイトル側で示されるため省略、単一系列は凡例なしで良いという
  // dataviz方針に合わせている)。
  function renderTrendLineChart(chart) {
    const categories = chart?.categories || [];
    const values = (chart.series && chart.series[0] && chart.series[0].values) || [];
    if (!categories.length || !values.length) return "<p>該当データがありません</p>";
    const unit = chart.unit || "";
    const W = 280, H = 90, PAD_L = 4, PAD_R = 4, PAD_T = 12, PAD_B = 4;
    const plotW = W - PAD_L - PAD_R, plotH = H - PAD_T - PAD_B;
    const nums = values.map((v) => Number(v) || 0);
    const max = Math.max(...nums, 0);
    const min = Math.min(...nums, 0);
    const range = max - min || 1;
    const stepX = categories.length > 1 ? plotW / (categories.length - 1) : 0;
    const pts = nums.map((v, i) => [
      PAD_L + stepX * i,
      PAD_T + plotH - ((v - min) / range) * plotH,
    ]);
    const zeroY = PAD_T + plotH - ((0 - min) / range) * plotH;
    const linePath = pts.map(([x, y], i) => `${i === 0 ? "M" : "L"}${x.toFixed(1)},${y.toFixed(1)}`).join(" ");
    const last = pts[pts.length - 1];
    const areaPath = `${linePath} L${last[0].toFixed(1)},${zeroY.toFixed(1)} L${pts[0][0].toFixed(1)},${zeroY.toFixed(1)} Z`;
    const dots = pts
      .map(([x, y], i) => {
        const r = i === pts.length - 1 ? 4 : 2.5;
        return `<circle cx="${x.toFixed(1)}" cy="${y.toFixed(1)}" r="${r}" class="aisb-trend-dot"/>`;
      })
      .join("");
    const lastLabel = `${Math.round(nums[nums.length - 1]).toLocaleString()}${unit}`;
    const labelAnchor = last[0] > W - 40 ? "end" : "middle";
    return `
      <svg viewBox="0 0 ${W} ${H}" class="aisb-trend-svg" preserveAspectRatio="none">
        <line x1="${PAD_L}" y1="${zeroY.toFixed(1)}" x2="${W - PAD_R}" y2="${zeroY.toFixed(1)}" class="aisb-trend-axis"/>
        <path d="${areaPath}" class="aisb-trend-area"></path>
        <path d="${linePath}" class="aisb-trend-line"></path>
        ${dots}
        <text x="${last[0].toFixed(1)}" y="${Math.max(10, last[1] - 8).toFixed(1)}" text-anchor="${labelAnchor}" class="aisb-trend-endlabel">${escapeHtml(lastLabel)}</text>
      </svg>
      <div class="aisb-trend-xlabels"><span>${escapeHtml(categories[0])}</span><span>${escapeHtml(categories[categories.length - 1])}</span></div>
    `;
  }

  // 状態分類の構成比(part-to-whole)を積み上げ横棒1本+凡例で表現する。
  // 与信リスク(正常/警戒/超過)・在庫逼迫(正常/逼迫/割れ)・滞留債権(延滞日数帯)向け。
  // ランキング棒だけでは「全体に対してどれくらいの割合が危険域か」が読めないため、
  // 棒グラフとは別ジョブ(part-to-whole)の表現として追加した(ai-api-server側の
  // distribution.slices は既存の .aisb-risk-* 配色と揃えた status(good/warning/critical)
  // を持つ)。色はテキストではなく凡例のドット(スウォッチ)側にのみ使う。
  const STATUS_COLOR = { good: "#0ca30c", warning: "#b8790a", critical: "#d03b3b" };
  function renderStatusDistributionChart(distribution) {
    const slices = (distribution && distribution.slices) || [];
    const total = slices.reduce((s, x) => s + (Number(x.count) || 0), 0);
    if (!total) return "";
    const bar = slices
      .filter((s) => s.count > 0)
      .map((s) => {
        const pct = (s.count / total) * 100;
        const color = STATUS_COLOR[s.status] || "#82888f";
        return `<div class="aisb-dist-seg" style="width:${pct.toFixed(2)}%;background:${color}" title="${escapeHtml(s.label)}: ${s.count}件(${Math.round(pct)}%)"></div>`;
      })
      .join("");
    const legend = slices
      .map((s) => {
        const color = STATUS_COLOR[s.status] || "#82888f";
        const pct = Math.round((s.count / total) * 100);
        return `<span class="aisb-dist-legend-item"><span class="aisb-legend-dot" style="background:${color}"></span>${escapeHtml(s.label)} ${s.count}件(${pct}%)</span>`;
      })
      .join("");
    return `
      <div class="aisb-section-title">${escapeHtml(distribution.title || "内訳")}</div>
      <div class="aisb-dist-bar">${bar}</div>
      <div class="aisb-dist-legend">${legend}</div>
    `;
  }

  return { CSS, escapeHtml, detectLegacyContext, renderChart, renderStatusDistributionChart };
})();
