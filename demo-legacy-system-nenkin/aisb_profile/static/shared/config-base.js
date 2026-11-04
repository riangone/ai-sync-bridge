// shared/config-base.js — 埋め込み版
// chrome-extension/shared/config-base.js の移植版。プロファイル/既定設定の読み込みと
// APIオリジン解決を担う。環境依存の差分は chrome.storage.local → localStorage のみ
// (詳細は modules/bootstrap.js 冒頭のコメント参照)。
window.AISB = window.AISB || {};

window.AISB.configBase = (function () {
  const STORAGE_KEY_PROFILE = "aisb_embed_activeProfile";
  const STORAGE_KEY_OPEN = "aisb_embed_sidebarOpen";

  function loadJSON(key, fallback) {
    try {
      const raw = localStorage.getItem(key);
      return raw === null ? fallback : JSON.parse(raw);
    } catch (e) {
      return fallback;
    }
  }
  function saveJSON(key, value) {
    try {
      localStorage.setItem(key, JSON.stringify(value));
    } catch (e) {
      // private mode 等でlocalStorageが使えない場合は無視(次回起動時に既定値へ戻るだけ)
    }
  }

  // 既定プロファイル。chrome-extension側の background.js DEFAULT_PROFILE /
  // shared/config-base.js と内容を揃える(新パネル追加時は3箇所とも更新すること)。
  const DEFAULT_PROFILE = {
    apiBaseUrl: "http://localhost:5051",
    sidebarWidthPx: 380,
    // AI関連機能に絞って表示する暫定措置(chrome-extension/shared/config-base.js と同じ
    // 理由・同じ内容。業務データ閲覧/顧客検索/通知/管理/ワークフローは単純なCRUD・
    // 一覧表示でAIを本質的には使わないため一時的にenabled:falseにしている)。
    panels: [
      { id: "chat", label: "AIチャット", enabled: true },
      { id: "legacy", label: "業務データ", enabled: false },
      { id: "nlsql", label: "AI検索", enabled: true },
      { id: "customers", label: "顧客検索", enabled: false },
      { id: "ocr", label: "OCR取込", enabled: true },
      { id: "search", label: "セマンティック検索", enabled: true },
      { id: "analytics", label: "予測分析", enabled: true },
      { id: "workflows", label: "ワークフロー", enabled: false },
      { id: "notifications", label: "通知", enabled: false },
      // Phase2/4追加分。chrome-extension/shared/config-base.js と同じ基準・同じ内容
      // (新パネル追加時は3箇所とも更新すること)。2026-08-20: 同期時に暫定falseを
      // 引き継いでいたのを是正、AI異常検知/AI提案/AIリスク診断を持つ機能を有効化。
      { id: "inventory", label: "在庫管理", enabled: true },
      { id: "purchase", label: "発注管理", enabled: true },
      { id: "profit", label: "利益・粗利", enabled: true },
      { id: "arap", label: "売掛買掛", enabled: true },
      { id: "alerts", label: "アラート", enabled: true },
      { id: "recommend", label: "類似検索", enabled: true },
      { id: "websearch", label: "企業・物件検索", enabled: false },
      // 査定・リスクAI(valuation)は不動産仲介(realestate)専用パネル
      // (Property/Viewingエンティティに依存)のため、本デモ(nenkin)では無効化する。
      { id: "valuation", label: "査定・リスクAI", enabled: false },
      { id: "assistant", label: "AIアシスタント", enabled: true },
      { id: "convinput", label: "自然言語入力", enabled: true },
      { id: "admin", label: "管理", enabled: false },
    ],
  };

  // legacyOrigin (このページの実オリジン) から対応するAPIオリジンを引く。
  // chrome-extension版と同じ理由: サーバー機ではlocalhost想定でも、公開ドメイン経由で
  // 開いている場合はそちらを優先する。
  const ORIGIN_API_MAP = {
    "http://localhost:5050": "http://localhost:5051",
    "https://aisync-nenkin.0101.click": "https://aisync-nenkin-api.0101.click",
    // aisync.0101.click/nenkin/* のサブパス公開構成(Caddyがhandle_path
    // /nenkin-api/*で5051へstrip_prefix転送する想定)。dealer/realestate/koseki版と同じパターン。
    "https://aisync.0101.click": "https://aisync.0101.click/nenkin-api",
  };

  // このコピーが属する業態("erp"|"dealer"|"realestate"|"koseki"|"nenkin")。パネルJS
  // (panel-web-search.js等)が共通コードのまま業態ごとに表示/機能を出し分けるための
  // 唯一の分岐点。ai-api-server側のsettings.instance(AISB_INSTANCE環境変数)と
  // 対応関係にあるが、こちらは埋め込み先のレガシー画面によって静的に決まるため
  // ハードコードでよい。
  const INSTANCE = "nenkin";

  // 年金相談業務システム(日本年金機構コールセンター/年金事務所窓口)全7業務エンティティ。
  // demo-legacy-system(製造業ERP版)のLEGACY_ENTITIESと同じ仕組みで、業務ドメインだけを
  // 年金相談(被保険者/適用事業所/年金請求)向けに置き換えたもの
  // (demo-legacy-system-nenkin/main.py の ENTITY_LABELS が唯一の情報源)。
  const LEGACY_ENTITIES = [
    { id: "Insured", label: "被保険者", hasDetail: true, cols: ["Id", "Name", "NameKana", "Address", "Status"] },
    { id: "Employer", label: "適用事業所", hasDetail: true, cols: ["Id", "Name", "Address", "MemberCount"] },
    { id: "EnrollmentRecord", label: "適用記録", hasDetail: true, cols: ["Id", "EmployerName", "PensionOffice", "PensionType"] },
    { id: "Staff", label: "相談員", hasDetail: true, cols: ["Id", "Name", "Department", "Position"] },
    { id: "PensionClaimRequest", label: "年金請求", hasDetail: true, cols: ["Id", "CustomerName", "OrderDate", "TotalAmount", "Status"] },
    { id: "CallReception", label: "来所・電話相談受付", hasDetail: true, cols: ["Id", "VisitorName", "Purpose", "ReceptionTime", "Status"] },
    { id: "ContributionHistory", label: "資格異動履歴", hasDetail: false, cols: ["ProductName", "Type", "Date"] },
  ];

  // chrome.storage.local.get() 相当。埋め込み版はコンテキスト無効化という概念が
  // 存在しない(ページと運命を共にする通常のスクリプト)ため、常に値を返す。
  async function loadContext() {
    const stored = loadJSON(STORAGE_KEY_PROFILE, null);
    // panels(どのパネルを表示するか)はユーザーがカスタマイズするUIが存在しない
    // コード管理の設定なので、保存済みプロファイルの他のフィールド(sidebarWidthPx等)は
    // 保持しつつ panels だけは常にDEFAULT_PROFILE側を優先する(chrome-extension版の
    // shared/config-base.js と同じ理由)。
    const profile = { ...DEFAULT_PROFILE, ...(stored || {}), panels: DEFAULT_PROFILE.panels };
    const sidebarOpen = loadJSON(STORAGE_KEY_OPEN, true);
    const API_BASE = ORIGIN_API_MAP[location.origin] || profile.apiBaseUrl;
    // サブパス公開時にmiddleware.pyが埋め込むwindow.AISB_BASE_PATHを補う
    // (demo-legacy-system-dealer側と同一パターン。現状ERP版はサブパス公開して
    // いないためこの値は常に""=従来通りlocation.originのみと同じ結果になる)。
    const LEGACY_ORIGIN = location.origin + (window.AISB_BASE_PATH || "");
    return { profile, sidebarOpen, API_BASE, LEGACY_ORIGIN };
  }

  return { DEFAULT_PROFILE, ORIGIN_API_MAP, LEGACY_ENTITIES, INSTANCE, loadContext, loadJSON, saveJSON, STORAGE_KEY_PROFILE, STORAGE_KEY_OPEN };
})();
