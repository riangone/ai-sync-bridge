// shared/demo-scenarios.js — demo-legacy-system-nenkin(年金相談業務/日本年金機構
// コールセンター・年金事務所窓口)版
// templates/ai_intro.html の「▶ 自動デモを見る」から shared/demo-scenario-engine.js に
// 渡す宣言的シナリオ定義。対象は読み取り・分析系のみ(選定理由は下記コメント参照)。
// panel-*.js のDOM構造(id/class)は他4業態(erp/dealer/realestate/koseki)版と完全に
// 共通のため、セレクタはそれらと同一。ラベル・入力例のみ年金相談業務(被保険者・
// 年金請求・来所/電話相談受付)に合わせてある。
//
// koseki版の反省を踏まえ、本ファイルは最初からnenkin向けに新規作成する(他業態の
// コピー流用による語彙の取り残しを防ぐ)。あわせて、nenkin instance では以下の
// シナリオを意図的に含めていない:
//   - xa/gen(AI検索タブの「定型レポート」「AIレポート生成」): cross_analysis_service.py の
//     定型レポート3種がCustomer/Invoice/Product/InventoryTransactionをハードコードしており、
//     nenkin側にこれらのエンティティが存在しないため実行すると404で例外落ちする
//     (koseki版と同一の既知未修整バグ)。自動デモに組み込むと必ず失敗するため除外。
//   - wscompany/wsproperty(企業・物件検索): panel-web-search.jsはconfig-base.jsで
//     enabled:falseにしており、nenkin instanceではサイドバーのタブ自体が存在しない。
//   - valuation(査定・リスクAI): 同じくenabled:false。
window.AISB = window.AISB || {};

window.AISB.demoScenarios = {
  inventory: {
    title: "請求書類用紙・案内リーフレットの在庫不足を1クリックで発見",
    doneText: "人気の書類用紙で在庫切れ間近のものが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "inventory", text: "「在庫管理」タブを自動で開きます…" },
      { type: "narrate", text: "裁定請求書用紙・年金手帳交付用リーフレットなどの在庫一覧は開くだけで自動表示されます" },
      { type: "narrate", text: "続けて「異常検知を実行」を押してみます" },
      { type: "click", selector: "#aisb-inv-anomaly-btn" },
      { type: "waitFor", selector: "#aisb-inv-anomalies .aisb-card, #aisb-inv-anomalies p" },
      { type: "highlight", selector: "#aisb-inv-anomalies" },
    ],
  },
  arap: {
    title: "窓口の未収・未払を1クリックで把握",
    doneText: "郵送案内の未収分や書類用紙発注の未払いのリスクが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "arap", text: "「売掛買掛」タブを自動で開きます…" },
      { type: "narrate", text: "「エイジング分析を実行」を押してみます" },
      { type: "click", selector: "#aisb-arap-run" },
      { type: "waitFor", selector: "#aisb-arap-result .aisb-card" },
      { type: "narrate", text: "郵送案内分の未収金・書類用紙発注の未払いをリスク(低/中/高)別に自動集計しました" },
      { type: "narrate", text: "続けて「AIでリスクを解釈する」を押してみます" },
      { type: "click", selector: "#aisb-arap-insight-btn" },
      { type: "waitFor", selector: "#aisb-arap-insight .aisb-insight-card, #aisb-arap-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-arap-insight" },
    ],
  },
  analytics: {
    title: "相談・年金請求件数の予測グラフを1クリックで表示",
    doneText: "繁忙日の見通しが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "analytics", text: "「予測分析」タブを自動で開きます…" },
      { type: "waitFor", selector: "#aisb-forecast-chart .aisb-chart, #aisb-forecast-chart p" },
      { type: "highlight", selector: "#aisb-forecast-chart" },
      { type: "narrate", text: "開くだけで年金請求・相談受付件数の予測グラフ(線形回帰)が自動表示されました" },
      { type: "narrate", text: "続けて「AIでトレンドを解釈する」を押してみます" },
      { type: "click", selector: "#aisb-forecast-insight-btn" },
      { type: "waitFor", selector: "#aisb-forecast-insight .aisb-insight-card, #aisb-forecast-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-forecast-insight" },
    ],
  },
  alerts: {
    title: "見落としがちな滞留請求・再連絡待ちの相談を1クリックで確認",
    doneText: "何から対応すべきかが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "alerts", text: "「アラート」タブを自動で開きます…" },
      { type: "narrate", text: "「アラートを確認」を押してみます" },
      { type: "click", selector: "#aisb-alert-check" },
      { type: "waitFor", selector: "#aisb-alert-result .aisb-badge" },
      { type: "narrate", text: "滞留している年金請求と、再連絡待ちの相談受付をまとめて検知しました" },
      { type: "narrate", text: "続けて「AIで対応優先度を解釈する」を押してみます" },
      { type: "click", selector: "#aisb-alert-insight-btn" },
      { type: "waitFor", selector: "#aisb-alert-insight .aisb-insight-card, #aisb-alert-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-alert-insight" },
    ],
  },
  // AI検索タブは3サブタブ(定型レポート/AIレポート生成/自然文検索)のうち、nenkin instanceで
  // 実際に動作するのは自然文検索のみ(理由は本ファイル冒頭コメント参照)。デフォルト選択
  // エンティティ(#aisb-nlsql-entity)はLEGACY_ENTITIES[0]="Insured"のままにして、
  // 検索対象の切替操作を挟まずに済む質問文にしてある。
  nlsql: {
    title: "自然文検索を1クリックで体験",
    doneText: "日本語の条件が、安全な絞り込み条件に自動変換されました。",
    steps: [
      { type: "openPanel", panel: "nlsql", text: "「AI検索」タブの「自然文検索」を自動で開きます…" },
      { type: "click", selector: '.aisb-subtab[data-subtab="nlsql"]' },
      { type: "narrate", text: "日本語の条件を入力してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-nlsql-q", value: "北沢に住む被保険者を、生年月日の新しい順に5件" },
      { type: "narrate", text: "「AIで検索」を押すと、AIが安全な絞り込み条件に変換して検索します" },
      { type: "click", selector: "#aisb-nlsql-run" },
      { type: "waitFor", selector: "#aisb-nlsql-result .aisb-filter-summary", timeoutMs: 120000 },
      { type: "narrate", text: "AIが実際に適用した条件が画面に表示されるので安心です" },
      { type: "highlight", selector: "#aisb-nlsql-result" },
    ],
  },
  // OCR取込。デフォルトで選択される登録先は #aisb-ocr-entity の先頭オプション
  // (panel-ocr.js の OCR_ENTITY_SAMPLES.nenkin の1件目 = Insured(被保険者))。
  ocr: {
    title: "裁定請求書をOCRで読み取り、新規登録ページへの自動入力までを体験",
    doneText: "OCRで読み取った内容から、新規登録ページへの自動入力までを体験しました。保存は開いたタブ側でご自身の判断で行ってください(自動送信はしていません)。",
    steps: [
      { type: "openPanel", panel: "ocr", text: "「OCR取込」タブを自動で開きます…" },
      { type: "narrate", text: "デフォルトで選ばれている「被保険者」向けのテスト用サンプル画像をダウンロードします" },
      { type: "click", selector: "#aisb-ocr-sample-download" },
      {
        type: "waitForFileSelected",
        selector: "#aisb-ocr-file",
        text: "ここから先はブラウザの仕組み上、自動化できません。今ダウンロードした画像を、ハイライトされたファイル選択でご自身で読み込んでください",
        timeoutMs: 120000,
      },
      { type: "narrate", text: "ファイルが選択されました。続けて「OCR実行」を押してAIビジョンに読み取らせます" },
      { type: "click", selector: "#aisb-ocr-run" },
      { type: "waitFor", selector: "#aisb-ocr-register-area .aisb-ocr-register-btn", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-ocr-result" },
      { type: "narrate", text: "裁定請求書の中の項目をAIが読み取れました。続けて「登録用データを作る」を押してみます" },
      { type: "click", selector: "#aisb-ocr-register-area .aisb-ocr-register-btn" },
      { type: "waitFor", selector: "#aisb-ocr-register-area .aisb-ocr-normalized" },
      { type: "narrate", text: "レガシー画面の被保険者登録項目名に合わせた登録用データが自動生成されました" },
      { type: "highlight", selector: "#aisb-ocr-register-area .aisb-ocr-normalized" },
      {
        type: "clickReal",
        selector: "#aisb-ocr-register-area .aisb-ocr-autofill-btn",
        text: "ここから先はポップアップブロック対策のため、ハイライトされた「新規登録ページを開いて自動入力」をご自身でクリックしてください",
        timeoutMs: 60000,
      },
      {
        type: "waitForText",
        selector: "#aisb-ocr-register-area .aisb-ocr-autofill-status",
        contains: "入力",
        timeoutMs: 12000,
      },
      { type: "narrate", text: "被保険者登録の新規登録ページが開き、OCRで読み取った内容をもとに項目へ自動入力されました。内容を確認のうえ、開いたタブ側でご自身の判断で保存してください(自動送信はしていません)。" },
    ],
  },
};
