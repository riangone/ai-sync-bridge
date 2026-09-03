// shared/config-base.js
// プロファイル/既定設定の読み込みと、APIオリジン解決を担う。
// 他のモジュール(dom-base/api-base/ui-base/modules/panel-*)はこのファイルより
// 後に manifest.json content_scripts.js の配列順で読み込まれる前提。
// (MV3のcontent scriptは同一分離ワールド内で複数ファイルを順番に評価するだけの
// クラシックスクリプトなので、トップレベルの `window.AISB.xxx` 代入はファイルを
// またいで共有できる。ビルドツール/バンドラは使わない。)
window.AISB = window.AISB || {};

window.AISB.configBase = (function () {
  // 既定プロファイル。background.js の DEFAULT_PROFILE / profiles/template/profile.json
  // と3箇所で内容を揃える必要がある(いずれもインストール直後・ストレージ未設定時の
  // フォールバックとして使われるため)。新しいパネルを追加したら3箇所とも更新すること。
  const DEFAULT_PROFILE = {
    apiBaseUrl: "http://localhost:5011",
    sidebarWidthPx: 380,
    // AI関連機能に絞って表示する暫定措置(業務データ閲覧/顧客検索/通知/管理/ワークフローは
    // 単純なCRUD・一覧表示でAIを本質的には使わないため一時的にenabled:falseにしている。
    // 復活させたい場合はここをtrueに戻すだけでよい、パネル自体は削除していない)。
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
      // Phase2/4追加分(Task#1-4/#7)。同期時にlegacy/customers/notifications等の暫定false
      // をそのまま引き継いでいたが、実際はAI異常検知(inventory)・AI発注提案(purchase)・
      // AIリスク診断(arap/alerts)・AI検索+正規化(websearch)を持つ機能であり、
      // analytics/recommendと同じ基準で有効化(2026-08-20)。profitは既存analyticsと同待遇
      // (レポート系はUI一覧に含める方針で統一)。
      { id: "inventory", label: "在庫管理", enabled: true },
      { id: "purchase", label: "発注管理", enabled: true },
      { id: "profit", label: "利益・粗利", enabled: true },
      { id: "arap", label: "売掛買掛", enabled: true },
      { id: "alerts", label: "アラート", enabled: true },
      { id: "recommend", label: "類似検索", enabled: true },
      { id: "websearch", label: "企業・物件検索", enabled: true },
      { id: "assistant", label: "AIアシスタント", enabled: true },
      { id: "convinput", label: "自然言語入力", enabled: true },
      { id: "admin", label: "管理", enabled: false },
    ],
  };

  // legacyOrigin (このページの実オリジン) から対応するAPIオリジンを引く。
  // 保存済みprofile.apiBaseUrlはインストール時点の固定値のため、例えばサーバー機では
  // localhost想定で保存されていても、ユーザーが公開ドメイン経由で自分のPCから開いて
  // いる場合、localhost:5011はユーザー自身のPCを指してしまい接続不能になる。実際に
  // 開いているorigin (location.origin) を優先して解決する。
  const ORIGIN_API_MAP = {
    "http://localhost:5010": "http://localhost:5011",
    "https://aisync.0101.click": "https://aisync-api.0101.click",
  };

  // このコピーが対象とする業態("erp"|"dealer")。埋め込み版(aisb_embed/shared/config-base.js)
  // ではアプリごとに物理コピーが分かれるため単純ハードコードだが、拡張版は同一コードが
  // manifest.json content_scripts.matches に列挙したオリジンへ注入される仕組みなので、
  // ORIGIN_API_MAPと同じ考え方でorigin別に解決する(panel-nlsql.js/panel-web-search.js/
  // panel-conv-input.js が ctx.INSTANCE で業態別に中身を出し分ける、その唯一の分岐点)。
  // 現時点の manifest.json matches / host_permissions はERP側オリジン
  // (localhost:5010 / aisync.0101.click)のみで、dealer側オリジンは未登録のため、
  // このマップは実質常に空振りし INSTANCE は "erp" に解決される。dealer側のレガシー画面
  // にもこの拡張を注入したくなった場合は、ここへのエントリ追加に加えて manifest.json の
  // matches / host_permissions も更新すること(そちらは新規オリジンへのアクセス許可を
  // 増やす変更になるため、この分岐追加だけでは効果を持たない)。
  const ORIGIN_INSTANCE_MAP = {
    "http://localhost:5020": "dealer",
    "https://aisync-dealer.0101.click": "dealer",
  };
  const INSTANCE = ORIGIN_INSTANCE_MAP[location.origin] || "erp";

  // レガシーERP 6.3章 全13業務エンティティ。id はレガシー側ルーティング
  // (/{entity}/List, /{entity}/Detail/{id}) およびJSON API (/api/{entity}/list,
  // /api/{entity}/detail/{id}) のパスセグメントと一致させている。
  // hasDetail は「6.3章の画面一覧表でDetail列があるか」に合わせてあり、Product/
  // InventoryTransaction/GoodsReceipt/ArAp/Profit は一覧(または照会)のみのため false。
  // 業務データパネル(panel-legacy)とAI検索パネル(panel-nlsql)の両方で共有する。
  const LEGACY_ENTITIES = [
    { id: "Customer", label: "顧客", hasDetail: true, cols: ["Id", "Name", "Tel", "CreditLimit"] },
    { id: "Order", label: "受注", hasDetail: true, cols: ["Id", "CustomerName", "OrderDate", "TotalAmount", "Status"] },
    { id: "Product", label: "商品/在庫", hasDetail: false, cols: ["Id", "Name", "Category", "UnitPrice", "Stock"] },
    { id: "Supplier", label: "仕入先", hasDetail: true, cols: ["Id", "Name", "Category", "Tel"] },
    { id: "Employee", label: "従業員", hasDetail: true, cols: ["Id", "Name", "Department", "Position"] },
    { id: "Estimate", label: "見積", hasDetail: true, cols: ["Id", "CustomerName", "EstimateDate", "TotalAmount", "Status"] },
    { id: "Invoice", label: "請求", hasDetail: true, cols: ["Id", "CustomerName", "DueDate", "TotalAmount", "Status"] },
    { id: "PurchaseOrder", label: "発注", hasDetail: true, cols: ["Id", "SupplierName", "OrderDate", "TotalAmount", "Status"] },
    { id: "InventoryTransaction", label: "在庫トランザクション", hasDetail: false, cols: ["ProductName", "Type", "Quantity", "Date"] },
    { id: "GoodsReceipt", label: "入荷", hasDetail: false, cols: ["Id", "SupplierName", "ProductName", "Quantity", "ReceiptDate"] },
    { id: "Property", label: "物件", hasDetail: true, cols: ["Id", "Name", "Address", "Price"] },
    { id: "ArAp", label: "売掛買掛", hasDetail: false, cols: ["Type", "PartnerName", "Balance"] },
    { id: "Profit", label: "利益", hasDetail: false, cols: ["ProductName", "Sales", "Cost", "Gross", "GrossRate"] },
  ];

  // ストレージからプロファイル/開閉状態を読み込み、APIベースURLを解決する。
  // 拡張コンテキスト無効化時(再読み込み直後の古いタブ等)は null を返し、呼び出し側
  // (bootstrap.js)で静かに処理を打ち切れるようにする。
  async function loadContext() {
    if (!chrome.runtime?.id) return null;
    let activeProfile, sidebarOpen;
    try {
      ({ activeProfile, sidebarOpen } = await chrome.storage.local.get(["activeProfile", "sidebarOpen"]));
    } catch (e) {
      return null;
    }
    // panels(どのパネルを表示するか)はユーザーがカスタマイズするUIが存在しない
    // コード管理の設定なので、保存済みプロファイルの他のフィールド(sidebarWidthPx等の
    // ユーザー操作由来の状態)は保持しつつ、panelsだけは常にDEFAULT_PROFILE側を優先する。
    // こうしないと、新しいパネルの追加や有効/無効の変更(例: AI以外の機能を一時的に
    // 非表示にする)が既にストレージへ保存済みの古いプロファイルに反映されない。
    const profile = { ...DEFAULT_PROFILE, ...(activeProfile || {}), panels: DEFAULT_PROFILE.panels };
    const API_BASE = ORIGIN_API_MAP[location.origin] || profile.apiBaseUrl;
    // レガシーシステム自身が持つ読み取り専用JSONエンドポイント（/api/{entity}/list 等）。
    // 拡張は常にこのページと同一オリジンから注入されているので、同一オリジン取得
    // (=CORS不要) で今開いているレガシーシステムの実データを直接読める。
    const LEGACY_ORIGIN = location.origin;
    return { profile, sidebarOpen, API_BASE, LEGACY_ORIGIN };
  }

  return { DEFAULT_PROFILE, ORIGIN_API_MAP, LEGACY_ENTITIES, INSTANCE, loadContext };
})();
