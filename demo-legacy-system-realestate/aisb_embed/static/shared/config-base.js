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
    apiBaseUrl: "http://localhost:5031",
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
      { id: "websearch", label: "企業・物件検索", enabled: true },
      // 2026-09-08追加: 不動産仲介(realestate)専用。Property/Viewingエンティティに
      // 依存し、erp/dealerには存在しない業務のため、このconfig-base.js(realestate版)
      // にのみ追加する(3demo共通のchrome-extension側には追加しない)。
      { id: "valuation", label: "査定・リスクAI", enabled: true },
      { id: "assistant", label: "AIアシスタント", enabled: true },
      { id: "convinput", label: "自然言語入力", enabled: true },
      { id: "admin", label: "管理", enabled: false },
    ],
  };

  // legacyOrigin (このページの実オリジン) から対応するAPIオリジンを引く。
  // chrome-extension版と同じ理由: サーバー機ではlocalhost想定でも、公開ドメイン経由で
  // 開いている場合はそちらを優先する。
  const ORIGIN_API_MAP = {
    "http://localhost:5030": "http://localhost:5031",
    "https://aisync-realestate.0101.click": "https://aisync-realestate-api.0101.click",
    // aisync.0101.click/realestate/* のサブパス公開構成(Caddyがhandle_path
    // /realestate-api/*で5031へstrip_prefix転送する想定)。dealer版と同じパターン。
    "https://aisync.0101.click": "https://aisync.0101.click/realestate-api",
  };

  // このコピーが属する業態("erp"|"dealer"|"realestate")。パネルJS(panel-web-search.js等)
  // が共通コードのまま業態ごとに表示/機能を出し分けるための唯一の分岐点。
  // ai-api-server側のsettings.instance(AISB_INSTANCE環境変数)と対応関係にあるが、
  // こちらは埋め込み先のレガシー画面によって静的に決まるためハードコードでよい。
  // 2026-09-08時点でai-api-server側はまだ"realestate"分岐を持たず、instance未対応の
  // パネル(OCR/AI検索の業種別プリセット等)は"erp"相当のフォールバックで動作する
  // (各panel-*.js が `PRESETS[ctx.INSTANCE] || PRESETS.erp` の形で防御しているため)。
  const INSTANCE = "realestate";

  // 不動産仲介基幹システム 全13業務エンティティ。demo-legacy-system(製造業ERP版)の
  // LEGACY_ENTITIES と同じ仕組みで、業務ドメインだけを不動産仲介向けに置き換えたもの。
  const LEGACY_ENTITIES = [
    { id: "Customer", label: "顧客", hasDetail: true, cols: ["Id", "Name", "CustomerType", "Tel"] },
    { id: "Property", label: "物件", hasDetail: true, cols: ["Id", "Name", "PropertyType", "Address", "Price", "Status"] },
    { id: "Order", label: "契約", hasDetail: true, cols: ["Id", "CustomerName", "OrderDate", "TotalAmount", "Status"] },
    { id: "Estimate", label: "査定", hasDetail: true, cols: ["Id", "CustomerName", "EstimateDate", "TotalAmount", "Status"] },
    { id: "Viewing", label: "内見予約", hasDetail: true, cols: ["Id", "CustomerName", "PropertyName", "ViewingDate", "Status"] },
    { id: "Invoice", label: "請求", hasDetail: true, cols: ["Id", "CustomerName", "DueDate", "TotalAmount", "Status"] },
    { id: "PurchaseOrder", label: "工事発注", hasDetail: true, cols: ["Id", "SupplierName", "OrderDate", "TotalAmount", "Status"] },
    { id: "Supplier", label: "協力会社", hasDetail: true, cols: ["Id", "Name", "Category", "Tel"] },
    { id: "Employee", label: "担当エージェント", hasDetail: true, cols: ["Id", "Name", "Department", "Position"] },
    { id: "InventoryTransaction", label: "物件ステータス履歴", hasDetail: false, cols: ["ProductName", "Type", "Date"] },
    { id: "GoodsReceipt", label: "工事完了報告", hasDetail: false, cols: ["Id", "SupplierName", "PropertyName", "WorkDescription", "ReceiptDate"] },
    { id: "ArAp", label: "売掛買掛", hasDetail: false, cols: ["Type", "PartnerName", "Balance"] },
    { id: "Profit", label: "利益", hasDetail: false, cols: ["ProductName", "Sales", "Cost", "Gross", "GrossRate"] },
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
