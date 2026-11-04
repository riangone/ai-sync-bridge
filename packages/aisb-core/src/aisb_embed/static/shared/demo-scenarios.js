// shared/demo-scenarios.js — demo-legacy-system(基幹ERP)版
// templates/ai_intro.html の「▶ 自動デモを見る」から shared/demo-scenario-engine.js に
// 渡す宣言的シナリオ定義。対象は読み取り・分析系のみ(選定理由は README/設計メモ参照)。
// 各ステップの selector は aisb_embed/static/modules/panel-*.js のDOM構造に対応する。
window.AISB = window.AISB || {};

window.AISB.demoScenarios = {
  search: {
    title: "セマンティック検索を1クリックで体験",
    doneText: "完全一致でなくても、意味が近いデータをAIが探し出しました。",
    steps: [
      { type: "openPanel", panel: "search", text: "AIパネルの「セマンティック検索」タブを自動で開きます…" },
      { type: "narrate", text: "検索ボックスに条件を入力してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-search-input", value: "配送が遅れがちな取引先" },
      { type: "narrate", text: "「検索」を押すと、キーワードが多少あいまいでも意味で探し当てます" },
      { type: "click", selector: "#aisb-search-run" },
      { type: "waitFor", selector: "#aisb-search-results .aisb-badge", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-search-results" },
    ],
  },
  inventory: {
    title: "在庫の異常を1クリックで発見",
    doneText: "発注点を割った商品が一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "inventory", text: "「在庫管理」タブを自動で開きます…" },
      { type: "narrate", text: "在庫一覧は開くだけで自動表示されます" },
      { type: "narrate", text: "続けて「異常検知を実行」を押してみます" },
      { type: "click", selector: "#aisb-inv-anomaly-btn" },
      { type: "waitFor", selector: "#aisb-inv-anomalies .aisb-card, #aisb-inv-anomalies p" },
      { type: "highlight", selector: "#aisb-inv-anomalies" },
    ],
  },
  arap: {
    title: "売掛買掛のリスクを1クリックで把握",
    doneText: "未回収・支払予定のリスクが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "arap", text: "「売掛買掛」タブを自動で開きます…" },
      { type: "narrate", text: "「エイジング分析を実行」を押してみます" },
      { type: "click", selector: "#aisb-arap-run" },
      { type: "waitFor", selector: "#aisb-arap-result .aisb-card" },
      { type: "narrate", text: "取引先ごとの売掛・買掛をリスク(低/中/高)別に自動集計しました" },
      { type: "narrate", text: "続けて「AIでリスクを解釈する」を押してみます" },
      { type: "click", selector: "#aisb-arap-insight-btn" },
      { type: "waitFor", selector: "#aisb-arap-insight .aisb-insight-card, #aisb-arap-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-arap-insight" },
    ],
  },
  analytics: {
    title: "売上予測グラフを1クリックで表示",
    doneText: "先行きの見通しが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "analytics", text: "「予測分析」タブを自動で開きます…" },
      { type: "waitFor", selector: "#aisb-forecast-chart .aisb-chart, #aisb-forecast-chart p" },
      { type: "highlight", selector: "#aisb-forecast-chart" },
      { type: "narrate", text: "開くだけで売上予測グラフ(線形回帰)が自動表示されました" },
      { type: "narrate", text: "続けて「AIでトレンドを解釈する」を押してみます" },
      { type: "click", selector: "#aisb-forecast-insight-btn" },
      { type: "waitFor", selector: "#aisb-forecast-insight .aisb-insight-card, #aisb-forecast-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-forecast-insight" },
    ],
  },
  alerts: {
    title: "見落としがちな異常を1クリックで確認",
    doneText: "何から対応すべきかが一目でわかりました。",
    steps: [
      { type: "openPanel", panel: "alerts", text: "「アラート」タブを自動で開きます…" },
      { type: "narrate", text: "「アラートを確認」を押してみます" },
      { type: "click", selector: "#aisb-alert-check" },
      { type: "waitFor", selector: "#aisb-alert-result .aisb-badge" },
      { type: "narrate", text: "在庫異常と売掛買掛の高リスクをまとめて検知しました" },
      { type: "narrate", text: "続けて「AIで対応優先度を解釈する」を押してみます" },
      { type: "click", selector: "#aisb-alert-insight-btn" },
      { type: "waitFor", selector: "#aisb-alert-insight .aisb-insight-card, #aisb-alert-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-alert-insight" },
    ],
  },
  // AI検索タブの3機能(定型レポート/AIレポート生成/自然文検索)。panel-nlsql.jsは
  // サブタブ切替(タブ自体はopenPanelで開くだけでは自動で出ない)のため、各シナリオで
  // 対応する.aisb-subtabを明示的にクリックしてから操作する。いずれも読み取り専用の
  // 検索/集計であり、書き込み(新規登録等)を伴わないため全ステップを最後まで再生する。
  xa: {
    title: "与信リスクなどの定型レポートを1クリックで実行",
    doneText: "複数データを跨いだ集計を、AIの解釈つきで確認できました。",
    steps: [
      { type: "openPanel", panel: "nlsql", text: "「AI検索」タブの「定型レポート」を自動で開きます…" },
      { type: "click", selector: '.aisb-subtab[data-subtab="xa"]' },
      { type: "narrate", text: "与信リスク・在庫逼迫・滞留債権などを複数データ横断でワンクリック集計できます" },
      { type: "click", selector: '#aisb-xa-buttons button[data-report="credit-risk"]' },
      { type: "waitFor", selector: "#aisb-xa-result .aisb-card" },
      { type: "narrate", text: "顧客ごとの与信残高・使用率がリスク区分別に自動集計されました" },
      { type: "highlight", selector: "#aisb-xa-result" },
      { type: "waitFor", selector: "#aisb-xa-insight .aisb-insight-card, #aisb-xa-insight p", timeoutMs: 120000 },
      { type: "narrate", text: "結果が出ると同時に、AIの解釈も自動で表示されます" },
      { type: "highlight", selector: "#aisb-xa-insight" },
    ],
  },
  gen: {
    title: "AIレポート自動生成を1クリックで体験",
    doneText: "定型レポートにない切り口も、質問文からAIが集計方法を組み立てました。",
    steps: [
      { type: "openPanel", panel: "nlsql", text: "「AI検索」タブの「AIレポート生成」を自動で開きます…" },
      { type: "click", selector: '.aisb-subtab[data-subtab="gen"]' },
      { type: "narrate", text: "質問文を入力してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-gen-q", value: "業種別の与信限度額合計を高い順に" },
      { type: "narrate", text: "「AIでレポート生成」を押すと、集計元データ・結合・グループ化・集計方法をAIが自動で組み立てます" },
      { type: "click", selector: "#aisb-gen-run" },
      { type: "waitFor", selector: "#aisb-gen-result .aisb-card", timeoutMs: 120000 },
      { type: "narrate", text: "AIが組み立てた集計条件はそのまま画面に表示されるので安心です" },
      { type: "highlight", selector: "#aisb-gen-result" },
      { type: "waitFor", selector: "#aisb-gen-insight .aisb-insight-card, #aisb-gen-insight p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-gen-insight" },
    ],
  },
  nlsql: {
    title: "自然文検索を1クリックで体験",
    doneText: "日本語の条件が、安全な絞り込み条件に自動変換されました。",
    steps: [
      { type: "openPanel", panel: "nlsql", text: "「AI検索」タブの「自然文検索」を自動で開きます…" },
      { type: "click", selector: '.aisb-subtab[data-subtab="nlsql"]' },
      { type: "narrate", text: "日本語の条件を入力してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-nlsql-q", value: "与信限度額が100万円を超える顧客を、限度額の高い順に5件" },
      { type: "narrate", text: "「AIで検索」を押すと、AIが安全な絞り込み条件に変換して検索します" },
      { type: "click", selector: "#aisb-nlsql-run" },
      { type: "waitFor", selector: "#aisb-nlsql-result .aisb-filter-summary", timeoutMs: 120000 },
      { type: "narrate", text: "AIが実際に適用した条件が画面に表示されるので安心です" },
      { type: "highlight", selector: "#aisb-nlsql-result" },
    ],
  },
  // 企業・物件検索(panel-web-search.js)。ここは「書き込み系」パネルであり、
  // demo-scenario-engine.js冒頭のコメント(=auto-input-engine.jsと同じ境界: 反映は
  // しても送信しない)の対象そのものだが、「新規登録ページを開いて自動入力」は
  // window.open()を伴うため、演示エンジンのel.click()(信頼されたユーザー操作の
  // 発火から数秒後・複数のsleep越し)から呼ぶとポップアップブロックの対象になり得る。
  // そのため演示は「登録用データを作る」(=自パネル内のPOSTのみ、レガシー側には一切
  // 触れない)までとし、新規タブを開く最終操作はユーザー自身のクリックに委ねる。
  // 「新規登録ページを開いて自動入力」(=window.open()を伴うopenAndFill)は、演示エンジンの
  // clickRealステップで最後の1クリックだけ本物のユーザー操作に委ねている(ポップアップ
  // ブロック対策。詳細はdemo-scenario-engine.js冒頭コメント参照)。それ以外は自動再生する。
  wscompany: {
    title: "会社検索から新規登録ページへの自動入力までを1クリックで体験",
    doneText: "会社検索から新規登録ページへの自動入力までを体験しました。保存は開いたタブ側でご自身の判断で行ってください(自動送信はしていません)。",
    steps: [
      { type: "openPanel", panel: "websearch", text: "「企業・物件検索」タブの「会社検索」を自動で開きます…" },
      { type: "click", selector: '.aisb-subtab[data-sub="company"]' },
      { type: "narrate", text: "会社名で検索してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-ws-company-kw", value: "トヨタ自動車" },
      { type: "narrate", text: "「検索」を押すと、外部情報も含めて自動で調べます" },
      { type: "click", selector: "#aisb-ws-company-run" },
      { type: "waitFor", selector: "#aisb-ws-company-result .aisb-card, #aisb-ws-company-result p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-ws-company-result" },
      { type: "narrate", text: "続けて「登録用データを作る」を押してみます" },
      { type: "click", selector: "#aisb-ws-company-result .aisb-ws-register-btn" },
      { type: "waitFor", selector: "#aisb-ws-company-result .aisb-ws-normalized" },
      { type: "narrate", text: "レガシー画面の項目名に合わせた登録用データが自動生成されました" },
      { type: "highlight", selector: "#aisb-ws-company-result .aisb-ws-normalized" },
      {
        type: "clickReal",
        selector: "#aisb-ws-company-result .aisb-ws-autofill-btn",
        text: "ここから先はポップアップブロック対策のため、ハイライトされた「新規登録ページを開いて自動入力」をご自身でクリックしてください",
        timeoutMs: 60000,
      },
      {
        type: "waitForText",
        selector: "#aisb-ws-company-result .aisb-ws-autofill-status",
        contains: "入力",
        timeoutMs: 12000,
      },
      { type: "narrate", text: "新規登録ページが開き、検索結果をもとに項目へ自動入力されました。内容を確認のうえ、開いたタブ側でご自身の判断で保存してください(自動送信はしていません)。" },
    ],
  },
  wsproperty: {
    title: "物件検索から新規登録ページへの自動入力までを1クリックで体験",
    doneText: "物件検索から新規登録ページへの自動入力までを体験しました。保存は開いたタブ側でご自身の判断で行ってください(自動送信はしていません)。",
    steps: [
      { type: "openPanel", panel: "websearch", text: "「企業・物件検索」タブの「物件検索」を自動で開きます…" },
      { type: "click", selector: '.aisb-subtab[data-sub="property"]' },
      { type: "narrate", text: "物件名で検索してみます(この入力は自動デモです)" },
      { type: "setValue", selector: "#aisb-ws-property-kw", value: "六本木ヒルズ" },
      { type: "narrate", text: "「検索」を押すと、外部情報も含めて自動で調べます" },
      { type: "click", selector: "#aisb-ws-property-run" },
      { type: "waitFor", selector: "#aisb-ws-property-result .aisb-card, #aisb-ws-property-result p", timeoutMs: 120000 },
      { type: "highlight", selector: "#aisb-ws-property-result" },
      { type: "narrate", text: "続けて「登録用データを作る」を押してみます" },
      { type: "click", selector: "#aisb-ws-property-result .aisb-ws-register-btn" },
      { type: "waitFor", selector: "#aisb-ws-property-result .aisb-ws-normalized" },
      { type: "narrate", text: "レガシー画面の項目名に合わせた登録用データが自動生成されました" },
      { type: "highlight", selector: "#aisb-ws-property-result .aisb-ws-normalized" },
      {
        type: "clickReal",
        selector: "#aisb-ws-property-result .aisb-ws-autofill-btn",
        text: "ここから先はポップアップブロック対策のため、ハイライトされた「新規登録ページを開いて自動入力」をご自身でクリックしてください",
        timeoutMs: 60000,
      },
      {
        type: "waitForText",
        selector: "#aisb-ws-property-result .aisb-ws-autofill-status",
        contains: "入力",
        timeoutMs: 12000,
      },
      { type: "narrate", text: "新規登録ページが開き、検索結果をもとに項目へ自動入力されました。内容を確認のうえ、開いたタブ側でご自身の判断で保存してください(自動送信はしていません)。" },
    ],
  },
  ocr: {
    title: "伝票をOCRで読み取り、新規登録ページへの自動入力までを体験",
    doneText: "OCRで読み取った内容から、新規登録ページへの自動入力までを体験しました。保存は開いたタブ側でご自身の判断で行ってください(自動送信はしていません)。",
    steps: [
      { type: "openPanel", panel: "ocr", text: "「OCR取込」タブを自動で開きます…" },
      { type: "narrate", text: "デフォルトで選ばれている「会社(顧客)」向けのテスト用サンプル画像をダウンロードします" },
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
      { type: "narrate", text: "画像の中の項目をAIが読み取れました。続けて「登録用データを作る」を押してみます" },
      { type: "click", selector: "#aisb-ocr-register-area .aisb-ocr-register-btn" },
      { type: "waitFor", selector: "#aisb-ocr-register-area .aisb-ocr-normalized" },
      { type: "narrate", text: "レガシー画面の項目名に合わせた登録用データが自動生成されました" },
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
      { type: "narrate", text: "新規登録ページが開き、OCRで読み取った内容をもとに項目へ自動入力されました。内容を確認のうえ、開いたタブ側でご自身の判断で保存してください(自動送信はしていません)。" },
    ],
  },
};
