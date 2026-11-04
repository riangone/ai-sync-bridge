// shared/demo-scenarios.js — demo-legacy-system-koseki(自治体窓口/戸籍住民課)版
// templates/ai_intro.html の「▶ 自動デモを見る」から shared/demo-scenario-engine.js に
// 渡す宣言的シナリオ定義。対象は読み取り・分析系のみ(選定理由は README/設計メモ参照)。
// panel-*.js のDOM構造(id/class)は他3業態(erp/dealer/realestate)版と完全に共通のため、
// セレクタはそれらと同一。ラベル・入力例のみ窓口業務(住民・証明書交付申請・来庁受付)に
// 合わせてある。
//
// 2026-09-28: このファイルは元々realestate版の内容がそのまま複製されており(物件・顧客区分・
// ローン等の不動産語彙のまま)、koseki向けに一切adaptされていなかった欠落を修正した
// (「AI panelがkoseki demoに適応していない」という指摘の一部)。あわせて、koseki instance
// では以下のシナリオを意図的に含めていない:
//   - xa/gen(AI検索タブの「定型レポート」「AIレポート生成」): cross_analysis_service.py の
//     定型レポート3種がCustomer/Invoice/Product/InventoryTransactionをハードコードしており、
//     koseki側にこれらのエンティティが存在しないため実行すると404で例外落ちする
//     (別途report済みの未修整バグ)。自動デモに組み込むと必ず失敗するため除外。
//   - wscompany/wsproperty(企業・物件検索): panel-web-search.jsはconfig-base.jsで
//     enabled:falseにしており、koseki instanceではサイドバーのタブ自体が存在しない。
//   - valuation(査定・リスクAI): 同じくenabled:false。
window.AISB = window.AISB || {};

window.AISB.demoScenarios = {
  search: {
    title: "セマンティック検索を1クリックで体験",
    doneText: "完全一致でなくても、文字列が近い住民を探し出しました。",
    steps: [
      { type: "openPanel", panel: "search", text: "AIパネルの「セマンティック検索」タブを自動で開きます…" },
      { type: "narrate", text: "検索ボックスに条件を入力してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-search-input", value: "北沢に住む高齢の住民" },
      { type: "narrate", text: "「検索」を押すと、キーワードが多少あいまいでも意味で探し当てます" },
      { type: "click", selector: "#aisb-search-run" },
      { type: "waitFor", selector: "#aisb-search-results .aisb-badge", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-search-results" },
    ],
  },
  inventory: {
    title: "収入証紙・帳票在庫の不足を1クリックで発見",
    doneText: "人気の証紙・帳票で在庫切れ間近のものが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "inventory", text: "「在庫管理」タブを自動で開きます…" },
      { type: "narrate", text: "収入証紙・戸籍謄本用紙などの在庫一覧は開くだけで自動表示されます" },
      { type: "narrate", text: "続けて「異常検知を実行」を押してみます" },
      { type: "click", selector: "#aisb-inv-anomaly-btn" },
      { type: "waitFor", selector: "#aisb-inv-anomalies .aisb-card, #aisb-inv-anomalies p" },
      { type: "highlight", selector: "#aisb-inv-anomalies" },
    ],
  },
  arap: {
    title: "窓口の未収金・未払を1クリックで把握",
    doneText: "郵送請求の未収手数料や証紙・帳票の未払いのリスクが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "arap", text: "「売掛買掛」タブを自動で開きます…" },
      { type: "narrate", text: "「エイジング分析を実行」を押してみます" },
      { type: "click", selector: "#aisb-arap-run" },
      { type: "waitFor", selector: "#aisb-arap-result .aisb-card" },
      { type: "narrate", text: "郵送請求の未収手数料・証紙や帳票の未払いをリスク(低/中/高)別に自動集計しました" },
      { type: "narrate", text: "続けて「AIでリスクを解釈する」を押してみます" },
      { type: "click", selector: "#aisb-arap-insight-btn" },
      { type: "waitFor", selector: "#aisb-arap-insight .aisb-insight-card, #aisb-arap-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-arap-insight" },
    ],
  },
  analytics: {
    title: "来庁・交付申請件数の予測グラフを1クリックで表示",
    doneText: "繁忙日の見通しが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "analytics", text: "「予測分析」タブを自動で開きます…" },
      { type: "waitFor", selector: "#aisb-forecast-chart .aisb-chart, #aisb-forecast-chart p" },
      { type: "highlight", selector: "#aisb-forecast-chart" },
      { type: "narrate", text: "開くだけで証明書交付申請・来庁件数の予測グラフ(線形回帰)が自動表示されました" },
      { type: "narrate", text: "続けて「AIでトレンドを解釈する」を押してみます" },
      { type: "click", selector: "#aisb-forecast-insight-btn" },
      { type: "waitFor", selector: "#aisb-forecast-insight .aisb-insight-card, #aisb-forecast-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-forecast-insight" },
    ],
  },
  alerts: {
    title: "見落としがちな滞留申請・呼出不応答を1クリックで確認",
    doneText: "何から対応すべきかが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "alerts", text: "「アラート」タブを自動で開きます…" },
      { type: "narrate", text: "「アラートを確認」を押してみます" },
      { type: "click", selector: "#aisb-alert-check" },
      { type: "waitFor", selector: "#aisb-alert-result .aisb-badge" },
      { type: "narrate", text: "滞留している証明書交付申請と、呼出不応答の来庁受付をまとめて検知しました" },
      { type: "narrate", text: "続けて「AIで対応優先度を解釈する」を押してみます" },
      { type: "click", selector: "#aisb-alert-insight-btn" },
      { type: "waitFor", selector: "#aisb-alert-insight .aisb-insight-card, #aisb-alert-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-alert-insight" },
    ],
  },
  // AI検索タブは3サブタブ(定型レポート/AIレポート生成/自然文検索)のうち、koseki instanceで
  // 実際に動作するのは自然文検索のみ(理由は本ファイル冒頭コメント参照)。デフォルト選択
  // エンティティ(#aisb-nlsql-entity)はLEGACY_ENTITIES[0]="Resident"のままにして、
  // 検索対象の切替操作を挟まずに済む質問文にしてある。
  nlsql: {
    title: "自然文検索を1クリックで体験",
    doneText: "日本語の条件が、安全な絞り込み条件に自動変換されました。",
    steps: [
      { type: "openPanel", panel: "nlsql", text: "「AI検索」タブの「自然文検索」を自動で開きます…" },
      { type: "click", selector: '.aisb-subtab[data-subtab="nlsql"]' },
      { type: "narrate", text: "日本語の条件を入力してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-nlsql-q", value: "北沢に住む住民を、生年月日の新しい順に5件" },
      { type: "narrate", text: "「AIで検索」を押すと、AIが安全な絞り込み条件に変換して検索します" },
      { type: "click", selector: "#aisb-nlsql-run" },
      { type: "waitFor", selector: "#aisb-nlsql-result .aisb-filter-summary", timeoutMs: 120000 },
      { type: "narrate", text: "AIが実際に適用した条件が画面に表示されるので安心です" },
      { type: "highlight", selector: "#aisb-nlsql-result" },
    ],
  },
  // OCR取込。デフォルトで選択される登録先は #aisb-ocr-entity の先頭オプション
  // (panel-ocr.js の OCR_ENTITY_SAMPLES.koseki の1件目 = Resident(住民))。
  ocr: {
    title: "住民票交付申請書をOCRで読み取り、新規登録ページへの自動入力までを体験",
    doneText: "OCRで読み取った内容から、新規登録ページへの自動入力までを体験しました。保存は開いたタブ側でご自身の判断で行ってください(自動送信はしていません)。",
    steps: [
      { type: "openPanel", panel: "ocr", text: "「OCR取込」タブを自動で開きます…" },
      { type: "narrate", text: "デフォルトで選ばれている「住民」向けのテスト用サンプル画像をダウンロードします" },
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
      { type: "narrate", text: "住民票交付申請書の中の項目をAIが読み取れました。続けて「登録用データを作る」を押してみます" },
      { type: "click", selector: "#aisb-ocr-register-area .aisb-ocr-register-btn" },
      { type: "waitFor", selector: "#aisb-ocr-register-area .aisb-ocr-normalized" },
      { type: "narrate", text: "レガシー画面の住民登録項目名に合わせた登録用データが自動生成されました" },
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
      { type: "narrate", text: "住民登録の新規登録ページが開き、OCRで読み取った内容をもとに項目へ自動入力されました。内容を確認のうえ、開いたタブ側でご自身の判断で保存してください(自動送信はしていません)。" },
    ],
  },
};
