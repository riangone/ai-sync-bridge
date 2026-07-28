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

  return { DEFAULT_PROFILE, ORIGIN_API_MAP, LEGACY_ENTITIES, loadContext };
})();
