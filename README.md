下記理解して

AI-Sync Bridge: Legacy System Modernization Platform
完全実装仕様書（言語非依存版）

このドキュメントは、AIによるレガシーシステムモダナイゼーションプラットフォーム「AI-Sync Bridge」の完全な実装仕様を定義します。開発言語に依存しない概念設計として記述しており、あらゆる言語（Python, Node.js/TypeScript, Go, Java, Rust 等）で実装可能です。
他のAIエージェントがこの仕様に従って同一のコードベースを再現できることを目的としています。

1. プロジェクト概要
1.1 コンセプト
既存のレガシーシステムを一切変更せずに、AI機能（OCR・セマンティック検索・自然言語検索・予測分析・自動化）を付与する
Chrome拡張機能がレガシーWeb UIにAIサイドバーを注入し、ローカルAPIサーバーがAIサービスを提供
プロファイルベースの拡張性により、あらゆるレガシーWebシステムに対応可能
1.2 全体アーキテクチャ
┌──────────────────────────────┐     ┌──────────────────────────────┐
│   Chrome Extension           │     │   AI API Server              │
│   (Manifest V3)              │◄───►│   (任意の言語で実装)          │
│   - Shadow DOM UI            │HTTP │   - API エンドポイント群      │
│   - 14+ Panel Modules        │     │   - ビジネスロジック層        │
│   - Profile-based config     │     │   - マルチAIプロバイダ対応    │
│   - Chart.js visualization   │     │   - ベクトル検索エンジン      │
└──────────────────────────────┘     └───────┬──────────────────────┘
                                              │
                          ┌───────────────────┼───────────────────┐
                          ▼                   ▼                   ▼
              ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
              │ Legacy System│    │   OpenCode   │    │   OpenAI /   │
              │ (未改変)      │    │   CLI (Local)│    │   Gemini API │
              │  または       │    │   AI Models  │    │   (Cloud)    │
              │ 模擬デモシステム │    └──────────────┘    └──────────────┘
              └──────────────┘

1.3 3つのサブシステム

本プロジェクトは以下の3つの独立したサブシステムから構成される：

#	サブシステム	役割	ユーザーが操作するもの
1	Chrome拡張機能	レガシーWeb UIにAIサイドバーを注入	Chromeブラウザの拡張機能
2	AI APIサーバー	AI機能・データ検索・ビジネスロジックを提供するバックエンド	HTTP APIサーバー（localhost:5001）
3	デモレガシーシステム	実際のレガシーシステムを模擬したWebアプリケーション	Webブラウザで操作するERP風UI（localhost:5000）
2. 推奨テクノロジースタック（言語非依存）

「この言語でなければならない」という制約はないが、以下の組み合わせが実績上推奨される。

レイヤー	推奨技術	代替案	備考
AI APIサーバー	Python (FastAPI/Flask) または Node.js (Express) / TypeScript	Go (Gin), Java (Spring Boot), Rust (Actix)	HTTP API + 外部AI呼び出しが中心
デモレガシーシステム	任意のWebフレームワーク	—	単なる模擬UI＋簡易データストア
データベース	SQLite（開発用） / PostgreSQL（本番用）	MySQL, SQL Server	ベクトル拡張があるものが望ましい
ORM / DBアクセス	言語標準のDBドライバ	Dapper相当、EF Core相当、Prisma等	軽量なマイクロORM推奨
ベクトル検索（高速）	sqlite-vec または pgvector	ChromaDB, Qdrant, FAISS	本番は専用ベクトルDBも可
ベクトル検索（フォールバック）	自作ANN（ランダム射影）	—	外部依存ゼロで動作可能
埋め込み（ローカル）	sentence-transformers (Python)	ONNX Runtime, llama.cpp	多言語対応モデル推奨
埋め込み（クラウド）	OpenAI / Gemini Embedding API	—	品質重視の場合
LLM（ローカル）	OpenCode CLI	llama.cpp, ollama	CLI経由で任意のモデルを利用
LLM（クラウド）	OpenAI / Gemini Chat API	Anthropic, Cohere	—
フロントエンド	Vanilla JavaScript + Shadow DOM	—	Chrome拡張の標準形式
グラフ描画	Chart.js	ECharts, D3.js	軽量であることが重要
認証（本番）	JWT Bearer	Session-based, OAuth2	
2.1 重要: 実装言語の選択基準

どの言語を選ぶ場合でも、以下の機能要件を満たす必要がある：

HTTPサーバー: RESTful APIをホストできること
非同期処理: AI呼び出しやDB操作を非同期で実行できること
外部プロセス管理: CLIツール（OpenCode CLI等）を子プロセスとして実行・制御できること
JSONシリアライズ/デシリアライズ: 複雑なネスト構造に対応できること
SQL実行: 動的SQLの構築とパラメータ化クエリが可能であること
ベクトル演算: float配列のコサイン類似度計算等が効率的に行えること
3. ディレクトリ構造（概念）
/
├── chrome-extension/                    # Chrome拡張機能 (Manifest V3)
│   ├── manifest.json                    # 拡張機能マニフェスト（権限・content_scripts定義）
│   ├── styles/overlay.css               # 共有オーバーレイスタイル
│   ├── icons/                           # アイコン (16/48/128px)
│   ├── lib/chart.umd.min.js             # Chart.js ライブラリ
│   ├── shared/                          # コア再利用可能モジュール
│   │   ├── config-base.js               # 設定管理クラス
│   │   ├── api-base.js                  # HTTPクライアント
│   │   ├── dom-base.js                  # DOM操作ユーティリティ
│   │   ├── auto-input-engine.js         # 自動入力エンジン
│   │   └── ui-base.js                   # UIコンポーネント基底
│   ├── profiles/template/               # 新規システム用テンプレート
│   │   └── profile.js / content-script.js / background.js
│   └── profiles/legacy-demo/            # デモシステム用プロファイル
│       ├── profile.js                   # システム固有設定
│       ├── content-script.js            # メイン注入スクリプト
│       ├── background.js                # サービスワーカー
│       ├── system-config.js             # 拡張設定モジュール
│       ├── sidebar-template.js          # サイドバーHTMLテンプレート
│       ├── sidebar-css.js               # Shadow DOM CSS
│       └── modules/                     # サイドバーパネルモジュール（14+）
│
├── ai-api-server/                       # AI APIサーバー（任意の言語）
│   ├── config/                          # 設定ファイル
│   ├── controllers/                     # APIエンドポイント（ルーティング）
│   ├── services/                        # ビジネスロジック
│   ├── models/                          # データモデル／DTO
│   ├── infrastructure/                  # 共通インフラ（DB接続、AIクライアント等）
│   └── data/                            # データベースファイル
│
└── demo-legacy-system/                  # デモ用模擬レガシーシステム（任意の言語）
    ├── controllers/                     # Web画面のルーティング
    ├── views/                           # HTMLテンプレート（WebForms風）
    ├── data/                            # データアクセス層
    └── public/                          # 静的ファイル（CSS/JS）

4. Chrome拡張機能 実装仕様

このセクションはフロントエンド（Vanilla JavaScript + Chrome Extension Manifest V3）であり、言語非依存の対象外。実装は指定のJSコードに従う。

4.1 shared/ モジュール詳細
4.1.1 ExtensionConfig（shared/config-base.js）
役割: 設定管理クラス
グローバル公開: window.ExtensionConfig
プロパティ:
apiBaseUrl: APIサーバーのベースURL（デフォルト http://localhost:5001）
detailLinkResolvers: {name: resolverFn} の辞書
screenTypeDetectors: detectorFn の配列
メソッド:
resolveDetailLink(tableName, id) → URL文字列 または null
全resolverFnを順次呼び出し、最初に非nullを返したものを採用
detectScreenType(url, title) → 画面種別文字列 または 'unknown'
全detectorFnを順次呼び出し、最初に非nullを返したものを採用
addDetailLinkResolver(name, resolverFn): resolverFn は (tableName, id) => url | null
addScreenTypeDetector(name, detectorFn): detectorFn は (url, title) => type | null
4.1.2 ApiBase（shared/api-base.js）
役割: 汎用HTTPクライアント
メソッド:
request(method, path, body?): コアメソッド。Content-Type: application/json でfetch。レスポンスJSONを自動パース。エラー時はレスポンス本文先頭200文字をErrorに含める
get(path, params?): GET。paramsをURLSearchParamsに変換
post(path, body), put(path, body), del(path)
fileToBase64(file): Fileオブジェクト → Base64文字列（FileReader使用）
4.1.3 DomBase（shared/dom-base.js）
役割: レガシーWebページのDOM操作ユーティリティ（全メソッドは静的）
extractFormData(): 全 input[name], select[name], textarea[name] を走査し、{name: {value, type, label}} を返す。ラベルは findLabel(input) で解決
findLabel(input): 以下の優先順位でラベル特定
label[for="input.id"] のテキスト
親 td/div/span 内の label テキスト
直前の兄弟 label 要素
テーブルの場合は列ヘッダー（th）のテキスト
extractTableData(): 全 table 要素から [{headers, rows}] を抽出
getScreenContext(config): URL, screenType, title, formFields, tableData を含む画面コンテキストを返す
setFieldValue(fieldName, value): 以下の優先順位で要素を特定し値を設定
input[name="{fieldName}"]
input[id*="{fieldName}"]
select[name="{fieldName}"]
textarea[name="{fieldName}"]
フォールバック: input[id$="..."], select[id*="..."], select[id$="..."]
select要素: setSelectValue で値/テキスト/部分一致/セグメント分割一致の4段階マッチング
設定後: triggerChange(el) で input/changeイベント発火（jQuery互換＋onchange直接呼び出し）
設定後: highlightField(el) で緑色ハイライト（2秒フェードアウト）
4.1.4 AutoInputEngine（shared/auto-input-engine.js）
役割: OCR抽出結果をレガシーシステムのフォームに自動入力
コンストラクタ: synonymMap（日本語ラベル→システムフィールド名の配列 のマッピング）
executeMappings(mappings): マッピングリストを順次実行（DomBase.setFieldValue呼び出し）
executeSmartMappings(extractedFields): 高度な自動入力エンジン
商品明細行の自動検出: 商品名1, 商品名2, 数量1, 数量2 等の連番パターンを認識
受注/見積画面では商品行を動的追加し、数量×単価の自動計算を実行
executeOrderSlip(extractedFields, orderItems?): 受注伝票専用
顧客名→ドロップダウン選択肢のあいまい一致
日付正規化（和暦→YYYY-MM-DD）
商品明細行のテーブル動的追加（_addProductRow）
既存行のHTMLテンプレートを <script> 内から抽出する方式
商品名からドロップダウン選択肢をあいまい一致で選択
選択後、単価・金額を自動計算・表示
matchFieldName(label, formData): 類義語辞書＋正規化比較であいまいマッチング
追加商品行のUI操作:
_addProductRow(item): <tr> を動的生成して #item-table-body に追加
商品ドロップダウンのHTMLテンプレートは、既存の <script> 内の addItem() 関数から抽出（新旧両対応）
数量変更時は金額セルを自動更新し、合計（#order-total / #estimate-total）を再計算
4.1.5 UiBase（shared/ui-base.js）
役割: AIサイドバーの共通UI操作
init(host, shadow, dialogHTML?): Shadow DOMにHTMLを注入、bodyに追加、イベント登録
attachEvents(): FABボタンの開閉、閉じるボタンのイベント
showStatus(msg, type): ステータスバー（クラスで色分け: info/ok/warn/error）
switchTab(tabId): タブ切り替え
renderTable(containerId, headers, rows, rowRender): テーブル描画（空の場合は「該当なし」表示）
4.2 profiles/legacy-demo/ の実装仕様
4.2.1 profile.js
役割: デモシステム固有の設定をグローバルに公開
設定内容:
apiBaseUrl: 'http://localhost:5001'
dialogTitle: 'AIアシスタント（デモ版）'
targetOrigin: 'http://localhost:5000'
tables: customers, orders, products の基本定義（テーブル名, ラベル, IDカラム, テキストカラム）
詳細リンク解決（6テーブル対応）: Customers→/Customer/Detail/{id}, Orders→/Order/Detail/{id}, Products→/Stock/Inquiry, Properties→/Property/Detail/{id}, Suppliers→/Supplier/Detail/{id}, Employees→/Employee/Detail/{id}
画面種別検出ルール（7ルール）: URLまたはタイトルに特定キーワードが含まれるかで判定
Order or 受注 → order-input
Stock or 在庫 → stock-inquiry
/Customer/Register or 新規登録 → customer-register
Customer or 顧客 → customer-mgmt
Product or 商品 → product-mgmt
Property or 物件 → property-register
類義語マップ（66エントリ）: 日本語ラベル→英語フィールド名の配列
例: '会社名': ['companyName', 'Name', 'CompanyName', 'company_name']
グローバル公開:
window.extensionConfig = config
window.extensionApi = api（ApiBaseインスタンス）
window.extensionAutoInput = autoInput（AutoInputEngineインスタンス）
4.2.2 content-script.js
役割: メイン注入エントリポイント。以下の順序で処理：
二重注入防止フラグ確認（window.__aiAssistantInjected）
Shadow DOM (mode: 'closed') の作成
CSS＋サイドバーHTMLをShadow DOMに注入
全モジュールの初期化呼び出し（initSidebar, initOcr, initWebSearch, initRecommend, initVectorSearch, initCrossSearch, initNaturalLanguageSearch, initReports, initForecast, initAlerts, initAssistant, initWorkflow, initConvInput, initPurchase, initInventory, initProfit, initArAp）
Chromeメッセージリスナー登録（GET_FORM_DATA / TOGGLE_SIDEBAR）
タブ切替・サブタブ切替イベント
状態復元→ページ離脱時に保存（beforeunload/pagehide）
再注入防止用MutationObserver
4.2.3 background.js
役割: サービスワーカー
機能: 30分間隔のアラートポーリング（chrome.alarms）、プッシュ通知サブスクリプション管理、タブ状態管理
4.2.4 sidebar-template.js
役割: サイドバーHTMLテンプレート（SIDEBAR_HTML 定数）
UI構成:
トグルボタン（画面左端にフローティング、クリックでサイドバー開閉）
サイドバー本体（右端から表示、幅260〜4096px可変、ドラッグリサイズ＋最大化ボタン）
メインタブ（上段に水平タブバー）:
OCR読取・自動入力 → サブタブ: 「読取・補正」「受注伝票」
Web検索 → サブタブ: 「会社検索」「物件検索」「仕入先検索」
類似推薦
AI検索 → サブタブ: 「ベクトル検索」「横断検索」「自然言語検索」「グラフ」
レポート → サブタブ: 「顧客」「受注」「在庫」「仕入先」「従業員」「見積」「請求」
予測分析 → サブタブ: 「需要予測」「売上トレンド」「与信リスク」
アラート
AIアシスタント
ワークフロー
会話入力
発注管理 → サブタブ: 「一覧」「作成」「AI提案」「仕入先評価」
在庫管理
利益・粗利
売掛・買掛
下部: ステータスバー（#ai-status）
4.2.5 sidebar-css.js
役割: Shadow DOM用CSS（AI_CSS 定数）
スタイル範囲: サイドバー配置（position: fixed, right: 0）、幅制御（CSS変数 --sidebar-w）、タブデザイン、ボタン、フォーム、テーブル、カード、スクロール、アニメーション
4.3 各パネルモジュールの実装仕様

全モジュールは即時実行関数形式で window.__panel 名前空間にinit関数を定義する。

panel-core.js
initSidebar(shadow, host):
幅永続化（chrome.storage.local.get/set('sidebarWidth')）
開閉状態永続化（chrome.storage.local.get/set('sidebarOpen')）
リサイズ機能: 左端のドラッグハンドル（#ai-resize-handle）のmousedown→mousemove/mouseupで幅変更
最大化機能: 最大化ボタンクリックで画面幅-40pxに拡大、window.resize時も追従
panel-utils.js
setStatus(shadow, msg, type): ステータスバーのテキスト＋クラス設定
handleSubmit(shadow, btnId, fn, state): ボタン連打防止（処理中はdisabled）＋ローディング表示＋エラーハンドリングのラッパー
renderMessage(container, msg, type): メッセージ表示（info/ok/warn/error）
saveSidebarData / restoreSidebarData: sessionStorage経由で以下の状態を保存/復元
選択中のタブ
検索結果
スクロール位置
OCR結果等の作業中データ
panel-state.js
セッション永続化機能: 状態管理の補助モジュール
panel-ocr.js
読取・補正タブ:
analyze-btn: ファイル選択→ api.fileToBase64(file) → POST /api/document/analyze（fileBase64, fileName, contentType, screenType, autoInput=true）→ 結果テーブル表示
auto-input-btn: state.lastOcrResult.extractedFields → window.extensionAutoInput.executeSmartMappings(fields) → 結果件数表示
report-btn: ファイル→ POST /api/document/report（fileBase64, fileName, contentType, analysisGoal）→ AIレポート表示
受注伝票サブタブ:
order-analyze-btn: ファイル→ POST /api/document/analyze（screenType='order-input'）→ 抽出フィールド＋商品明細行（パターンマッチ）を一覧表示
order-auto-input-btn: 前回結果→ executeSmartMappings
panel-web-search.js
会社検索: キーワード→ POST /api/company/search → 結果一覧→選択→ POST /api/company/register（選択データ）→ 自動入力
物件検索: キーワード→ POST /api/property/search → 結果→ POST /api/property/register
仕入先検索: キーワード→ POST /api/supplier/search → 結果→自動入力
panel-recommend.js
画面のテーブルから選択した行データ→ POST /api/recommend（tableName, id, maxResults, includeAiExplanation=true）→ 類似レコード＋AI説明表示
panel-search.js
ベクトル検索: クエリ→ POST /api/vector/search（query, tableName）→ 結果一覧＋AIサマリー表示
横断検索: キーワード→ POST /api/search/cross-table（keyword）→ テーブル別結果＋AIサマリー
自然言語検索: 質問文→ POST /api/query（query）→ 結果＋Chart.jsグラフ（棒/折れ線/円/ドーナツ/レーダー）
検索結果各行は config.resolveDetailLink(tableName, id) でリンク表示
panel-reports.js
各レポート種別（顧客/受注/在庫/仕入先/従業員/見積/請求）のボタン→ POST /api/{type}-report/report → 結果テーブル＋Chart.jsグラフ
panel-forecast.js
需要予測: POST /api/forecast/demand → 商品別予測一覧＋棒グラフ（現在庫/安全在庫/予測需要の積み上げ）
売上トレンド: POST /api/forecast/sales-trend → 月次推移折れ線グラフ
与信リスク: POST /api/forecast/credit-risk → 顧客別リスクスコア＋棒グラフ
panel-alerts.js
POST /api/push/check → アラート一覧表示（severity別色分け: high=赤, medium=黄, info=青）+ 各アラートの詳細リンク
panel-assistant.js
POST /api/local-ai/assist（message, screenContext, conversationId）→ 会話形式のチャットUI
画面コンテキスト（screenType, url, title, formData）を自動付与
履歴管理（最新20ターン）
リセットボタンで会話リセット
panel-workflow.js
GET /api/workflow → 一覧表示（有効/無効切替ボタン付き）
POST /api/workflow → 作成（名前, 説明, トリガー, ステップ）
PUT /api/workflow/{id} → 更新
DELETE /api/workflow/{id} → 削除
PATCH /api/workflow/{id}/toggle → 有効/無効切替
POST /api/workflow/{id}/execute → 実行状態表示
トリガー種別切替（schedule/screen_navigation/data_update/manual）
アクション種別追加（report/ocr/auto_input/push/chat/wait/condition）
panel-conv-input.js
自然言語入力→ POST /api/conversational-input（message, targetScreen, screenContext）→ 解析結果と不足フィールド表示
不足フィールドがなければ自動入力実行
panel-purchase.js
一覧: GET /api/purchase-order → テーブル表示
作成: POST /api/purchase-order（supplierName, orderDate, deliveryDate, items）→ 作成完了
AI提案: POST /api/purchase-order/ai-suggestions → AIが推奨する発注案
仕入先評価: POST /api/purchase-order/supplier-evaluation → 仕入先別評価スコア
panel-inventory.js
GET /api/inventory → 在庫トランザクション履歴一覧
POST /api/inventory/analyze → AI分析結果
POST /api/inventory/anomalies → 異常検知結果
panel-profit.js
POST /api/profit-report/report → 利益/粗利レポート＋グラフ
panel-arap.js
POST /api/ar-ap/aging → AR/APエイジングレポート＋AIリスク分析
5. AI APIサーバー 実装仕様（言語非依存）
5.1 アーキテクチャ概要

APIサーバーは以下の層構造を持つ：

HTTPリクエスト
    │
    ▼
┌─────────────┐     ┌─────────────┐     ┌─────────────┐
│ Controllers │────▶│  Services   │────▶│   Models    │
│ (ルーティング) │     │ (ビジネスロジック)│     │   (DTO)     │
└─────────────┘     └──────┬──────┘     └─────────────┘
                           │
              ┌────────────┼────────────┐
              ▼            ▼            ▼
    ┌────────────┐ ┌────────────┐ ┌────────────┐
    │   AI Client │ │    DB      │ │   CLI      │
    │  (OpenAI/   │ │ (SQLite/   │ │ (OpenCode  │
    │   Gemini)   │ │ PostgreSQL)│ │   等)      │
    └────────────┘ └────────────┘ └────────────┘

5.2 起動時処理（Program.cs相当）

サーバー起動時に以下の処理を順次実行する：

DIコンテナの構成: 後述のサービス一覧をDIコンテナに登録（Singleton/Scopedの区別を守る）
CORS設定: 任意のオリジン・メソッド・ヘッダーを許可（AllowAnyOrigin().AllowAnyMethod().AllowAnyHeader()）
認証設定: 本番モードの場合のみJWT認証を有効化（設定のKeyが空の場合は無効）
データベース初期化: 本番モードの場合、テーブルを作成
VectorCacheクリア: 本番モードの場合、起動時に古いキャッシュを削除
自動ベクターインデックス構築: 設定ファイルの SystemProfile:IndexTargets に定義された全テーブルに対して、各テキストカラムを連結→埋め込みベクトル化→インデックス登録
デモワークフローのシード: 4種類のワークフローテンプレートをメモリに投入
サーバー起動: ポート5001でHTTPリスニング開始
DI登録区分

Singleton（全リクエストで共有）:

AIクライアント（OpenCode CLIラッパー / OpenAI / Gemini）
ビジネスアシスタントサービス（会話履歴を保持）
DB接続ファクトリ
埋め込みサービス（E5 / n-gram）
ベクトル検索サービス
ベクトルインデックス（sqlite-vecローダー / ANNインデックス）
ワークフローエンジン
需要予測・売上トレンド・与信リスクサービス（統計データをキャッシュ可能）

Scoped（リクエストごとに生成）:

全レポートサービス（顧客/受注/在庫/仕入先/従業員/見積/請求/利益）
検索サービス
自動入力サービス
自然言語→SQL変換サービス
OCR分析サービス
会話型入力サービス
発注管理・在庫管理サービス
AR/APサービス
プッシュ通知・アラートチェックサービス
デモ/本番デュアルモード
デモモード（DemoMode: true）:
データベース不要。全データをインメモリのデータストアで管理
認証なし
起動が高速（DB初期化不要）
本番モード（DemoMode: false）:
実際のデータベース（SQLite / PostgreSQL等）を使用
JWT認証を有効化可能
テーブル自動作成
5.3 エンドポイント一覧（全コントローラ）
文書処理系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/document/analyze	fileBase64, fileName, contentType, screenType, autoInput	extractedFields, summary, autoInputPlan	OCR分析＋AI補正＋オプション自動入力計画
POST	/api/document/report	fileBase64, fileName, contentType, analysisGoal	detailedAnalysis, summary	文書画像→AI分析レポート生成
ベクトル検索系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/vector/build-index	tableName, idColumn, textColumns, whereClause?	indexedCount	ベクトルインデックス構築
POST	/api/vector/search	query, tableName?, maxResults?, scoreThreshold?	results[].{id,text,tableName,score}, aiSummary, totalCount	ベクトル類似度検索
検索系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/search/keyword	keyword, table?, filters?, conditions?, orderBy?, page?, pageSize?	results, totalCount, aiSummary?, chart?	キーワード＋条件検索
POST	/api/search/cross-table	keyword	テーブル別結果一覧, aiSummary	全テーブル横断検索
自然言語クエリ系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/query	query	sql?, results, chart?, aiSummary, error?	自然言語→SQL→結果→グラフ
AIチャット系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/local-ai/chat	message, systemPrompt?, temperature?, model?	response	単発AIチャット
POST	/api/local-ai/assist	message, screenContext, conversationId?	response, conversationId, suggestedActions[]	画面認識型ビジネスアシスタント
POST	/api/local-ai/analyze-image	imageBase64, prompt, mimeType?, model?	analysis	画像分析
GET	/api/local-ai/status	—	provider, model, available	AIプロバイダ状態確認
会話型入力系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/conversational-input	message, targetScreen, conversationId?, screenContext?	response, conversationId, inputMappings[], intent, missingFields[], confidence	自然言語→フォームデータ
外部データ検索系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/company/search	keyword	results[].{name, address, tel, ...}	企業情報検索（Web検索連携）
POST	/api/company/register	companyData	success	検索結果をレガシーシステムに登録
POST	/api/property/search	keyword	results[].{name, address, ...}	物件情報検索
POST	/api/property/register	propertyData	success	物件情報登録
レポート生成系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/customer-report/report	customerId?, period?	reportData, aiAnalysis, chart?	顧客レポート（与信・取引履歴）
POST	/api/order-report/report	period?, status?	reportData, aiAnalysis, chart?	受注レポート（状況・推移）
POST	/api/stock-report/report	category?	reportData, aiAnalysis, chart?	在庫レポート（現在庫・不足）
POST	/api/supplier-report/report	supplierId?	reportData, aiAnalysis, chart?	仕入先レポート
POST	/api/employee-report/report	department?	reportData, aiAnalysis	従業員レポート
POST	/api/estimate-report/report	period?, status?	reportData, aiAnalysis, chart?	見積レポート
POST	/api/invoice-report/report	period?, status?	reportData, aiAnalysis, chart?	請求レポート
予測分析系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/forecast/demand	category?	forecasts[], totalProducts, urgentReorderCount, executiveSummary?	需要予測（AI分析付き）
POST	/api/forecast/sales-trend	period?	monthlyData[], trend, growth, chart	売上トレンド分析
POST	/api/forecast/credit-risk	—	customerRisks[], highRiskCount, recommendation?	与信リスク予測
レコメンド系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/recommend	tableName, id, maxResults?, includeAiExplanation?	results[].{id, text, score, explanation?}	類似レコード推薦
発注管理系
メソッド	エンドポイント	リクエスト	レスポンス	説明
GET	/api/purchase-order	—	orders[]	発注一覧
POST	/api/purchase-order	supplierName, orderDate, deliveryDate, items[]	createdOrder	発注作成
POST	/api/purchase-order/ai-suggestions	—	suggestions[].{productName, suggestedQuantity, reason}	AI発注提案
POST	/api/purchase-order/supplier-evaluation	—	evaluations[].{supplierName, score, breakdown}	仕入先評価
在庫管理系
メソッド	エンドポイント	リクエスト	レスポンス	説明
GET	/api/inventory	productId?, period?	transactions[]	在庫トランザクション履歴
POST	/api/inventory/analyze	productId?	analysis, recommendations	AI在庫分析
POST	/api/inventory/anomalies	period?	anomalies[].{product, description, severity}	異常検知
入荷管理系
メソッド	エンドポイント	リクエスト	レスポンス	説明
GET	/api/goods-receipt	supplierId?, period?	receipts[]	入荷一覧
POST	/api/goods-receipt	supplierName, productName, quantity, receiptDate	createdReceipt	入荷登録
利益管理系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/profit-report/report	period?	profitData, productDetails[], totalProfit, aiAnalysis	利益レポート
AR/AP管理系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/ar-ap/aging	—	agingReport[], totalReceivable, totalPayable, aiAnalysis	売掛買掛エイジング
ワークフロー系
メソッド	エンドポイント	リクエスト	レスポンス	説明
GET	/api/workflow	—	workflows[]	ワークフロー一覧
POST	/api/workflow	workflowDefinition	createdWorkflow	ワークフロー作成
PUT	/api/workflow/{id}	workflowDefinition	updatedWorkflow	ワークフロー更新
DELETE	/api/workflow/{id}	—	success	ワークフロー削除
PATCH	/api/workflow/{id}/toggle	—	newEnabledState	有効/無効切替
POST	/api/workflow/{id}/execute	context?	executionResult	ワークフロー実行
POST	/api/workflow/evaluate-triggers	currentScreenType?, changedTable?	matchedWorkflows[]	トリガー評価
プッシュ通知系
メソッド	エンドポイント	リクエスト	レスポンス	説明
POST	/api/push/check	—	alerts[], totalAlerts, highCount, mediumCount, aiAnalysis?	アラートチェック
POST	/api/push/subscribe	endpoint, p256dh, auth, deviceName	success	プッシュ購読登録
POST	/api/push/unsubscribe	endpoint	success	プッシュ購読解除
GET	/api/push/subscriptions	—	subscriptions[]	購読一覧
分析履歴系
メソッド	エンドポイント	リクエスト	レスポンス	説明
GET	/api/analysis-history	type?, limit?	history[]	分析履歴一覧
POST	/api/analysis-history	type, query, result	createdHistory	分析履歴保存
5.4 主要サービスの実装仕様
5.4.1 AIクライアント（AiHttpClient相当）

AIプロバイダを透過的に切り替えるクライアント。以下のプロバイダをサポート：

OpenCode CLI（デフォルト、ローカル）: CLIツールを子プロセスとして実行
OpenAI API（クラウド）: 標準Chat Completion / Embeddings API
Gemini API（クラウド）: Gemini 2.5 FlashモデルのgenerateContent API

プロバイダ選択ロジック（設定ファイルの localCli.provider に基づく）:

"opencode" → OpenCode CLI経由
"gemini" または Gemini API Keyが設定済み → Gemini API
それ以外 → OpenAI API

共通メソッド:

chatAsync(systemPrompt, userPrompt, temperature?, model?) → 応答テキスト
getEmbeddingAsync(text) → float配列（ベクトル）
analyzeImageAsync(imageBase64, prompt, mimeType?, model?) → 分析テキスト

OpenCode CLIラッパーの実装詳細:

CLI実行: 子プロセス生成（opencode run "{prompt}" --format json [-m model] [-f file]）
標準出力からNDJSON（JSON Lines）を読み取り、type:"text" のpartを抽出
タイムアウト処理（設定可能、デフォルト120秒）
終了コード非0時はエラー
画像分析時: Base64を一時ファイルに保存→CLIの-fオプションで渡す→finallyで削除
CLIパス解決: 設定パス→npmグローバル→デフォルトパス

Gemini API呼び出しの実装詳細:

エンドポイント: POST https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent?key={apiKey}
リクエスト形式:
{
  "systemInstruction": {"parts": [{"text": "..."}]},
  "contents": [{"role": "user", "parts": [...]}],
  "generationConfig": {"temperature": 0.1, "responseMimeType": "application/json"}
}

画像送信時: parts 内に {inlineData: {mimeType, data}} を含める
エラー時: HTTPステータス＋エラー本文先頭500文字を例外に含める

OpenAI API呼び出しの実装詳細:

エンドポイント: POST https://api.openai.com/v1/chat/completions
Embeddings: POST https://api.openai.com/v1/embeddings
画像分析: content内に {type: "image_url", image_url: {url: "data:image/png;base64,...", detail: "high"}}
5.4.2 ビジネスアシスタント（BusinessAssistantService相当）

画面コンテキストを認識する会話型AIアシスタント。

処理フロー:

会話IDを元に履歴を管理（ConcurrentDictionary 等のスレッドセーフな構造）
システムプロンプトの動的構築:
システム名（設定から取得）
利用可能な機能一覧
システムの全テーブル一覧
現在の画面情報: 画面種別（日本語ラベル変換）、URL、タイトル、レコードID、フォーム入力値
ユーザープロンプトに画面情報をプレフィックスとして付加
AIチャット実行（temperature: 0.3）
履歴に追加（最大20ターン、超過時は古いものから削除）
レスポンスから推奨アクションを抽出（- または * で始まる行を最大5つ）
レスポンス＋会話ID＋推奨アクションを返却

画面種別→日本語ラベル変換:

order-input → "受注入力画面"
stock-inquiry → "在庫照会画面"
customer-register → "顧客新規登録画面"
customer-mgmt → "顧客管理画面"
等、全9種対応
5.4.3 埋め込みサービス（EmbeddingService相当）

データベースのテキストカラムをベクトル埋め込みに変換し、インデックスを構築・管理する。

インデックス方式（3層、優先順位順）:

sqlite-vec（最速）: SQLiteのvec0仮想テーブルを使用。外部DLLが必要
RandomProjectionIndex（ANN、中速）: ランダム射影による近似最近傍探索。純粋な言語実装で動作
VectorCacheテーブル/メモリキャッシュ（低速だが確実）: 全ベクトルとのコサイン類似度計算

インデックス構築手順:

指定テーブルからID＋テキストカラム連結値のリストを取得
各テキストをAI API経由でベクトル化（API失敗時は後述のローカル埋め込みにフォールバック）
ベースキャッシュ（VectorCacheテーブル/メモリキャッシュ）に保存
利用可能な最適化インデックス（sqlite-vec/RandomProjectionIndex）も構築

デモモード時: ConcurrentDictionary<string, EmbeddingCache> でインメモリ管理
本番モード時: VectorCacheテーブル（Id, TableName, OriginalText, EmbeddingJson, CreatedAt）を使用

5.4.4 ベクトル検索サービス（VectorSearchService相当）

クエリのベクトル検索を実行するオーケストレーター。

検索方式自動選択:

SQLite + sqlite-vec利用可能 → sqlite-vec 方式
ANNインデックス構築済み → random-projection 方式
上記以外 → brute-force 方式（全件コサイン類似度計算）

sqlite-vec検索の詳細:

クエリをベクトル化
SELECT id FROM vec_{tableName} WHERE embedding MATCH @query ORDER BY distance LIMIT @maxResults*3
取得したIDからVectorCacheでテキストを復元
正確なコサイン類似度を再計算（vec0は近似距離）
スコア閾値未満をフィルタリング
スコア降順で指定件数に絞り込み

ブルートフォース検索の詳細:

全VectorCacheを読み込み
各エントリとクエリベクトルのコサイン類似度を計算
閾値フィルタ→スコア降順ソート→上位N件

コサイン類似度計算式:

similarity = dot(a, b) / (sqrt(sum(a^2)) * sqrt(sum(b^2)) + 1e-10)


AIサマリー生成: 検索結果上位のテキストをAIに入力し、要約を生成

5.4.5 ローカル埋め込みサービス（LocalEmbeddingService相当）

AI APIが利用できない場合のフォールバック用埋め込み。

プロバイダ:

E5（高品質）: Pythonの sentence-transformers サイドカーを経由（intfloat/multilingual-e5-base、768次元）
Pythonプロセスとの通信はJSON Lines形式（stdin/stdout）
ドキュメント用とクエリ用でエンコード方式が異なる（isQueryフラグ）
n-gram（フォールバック、常に利用可能）:
1〜4グラムの部分文字列ごとにハッシュ値を計算
ハッシュ値を256次元ベクトルにマッピング（カウント）
L2正規化を実施
5.4.6 自動入力サービス（AutoInputService相当）

OCR抽出フィールドをWebフォームフィールドにマッピングする。

マッピング戦略（2段階）:

厳密一致（FindMatchingField）→ 確信度 "high":
フォームフィールド名（またはラベル）に抽出キーが含まれているか
類似一致（FindSimilarField）→ 確信度 "medium":
類義語辞書を仲介して間接的にマッチング
抽出キー→類義語群→フォームフィールド名の経路で一致

類義語辞書: 設定ファイルの SystemProfile.AutoInputMappings から読み込む。例：

{
  "会社名": ["CompanyName", "company_name", "Name"],
  "住所": ["Address", "所在地"],
  "TEL": ["Tel", "tel", "電話番号", "電話"]
}


設定がない場合はデフォルト辞書（約60エントリ）を使用。

CSSセレクタ生成: フィールド名が ctl00 で始まる→WebForms形式（input[name='...']）、それ以外→ input[id*='...']

文字列正規化: 小文字化＋空白/アンダースコア/ハイフンを除去して比較

5.4.7 自然言語→フォームデータ変換（ConversationalInputService相当）

ユーザーの自然言語入力からフォーム入力を生成する。

処理フロー:

画面種別に応じたシステムプロンプトを構築（利用可能フィールド一覧とJSONスキーマを含む）
AIにJSON形式でパースさせる
AIレスポンスからJSONを抽出（````json ブロックがあれば優先、なければ全文をパース試行）
抽出されたフィールドを ParsedIntent にマッピング
エンティティ解決: 顧客名/商品名があればDB検索で正式コードを解決
AutoInputService.GenerateAutoInputPlanAsync() でフォームマッピング生成
不足フィールド検出: 画面種別ごとの必須フィールドが揃っているか確認
レスポンステキスト＋マッピング＋不足フィールドリストを返却

画面種別別フィールド定義（5画面）:

order-input: 顧客名, 顧客コード, 商品名, 商品コード, 数量, 単価, 金額, 日付, 納期, 備考
customer-register: 会社名, カナ, TEL, 郵便番号, 住所, 与信限度額, 備考
estimate-mgmt: 顧客名, 顧客コード, 日付, 有効期限, 商品名, 数量, 単価, 金額
invoice-mgmt: 顧客名, 日付, 支払期日, 金額, 関連受注
supplier-mgmt: 仕入先名, TEL, 住所, 担当者, 与信枠
5.4.8 需要予測サービス（DemandForecastService相当）

ルールベースの需要予測＋AI分析。

予測アルゴリズム:

月別売上データを集計
商品ごとに:
過去の月平均出荷数量を計算（該当商品を含む注文の合計金額÷単価÷月数）
過去データがない場合は在庫/6をデフォルト値に
予測値 = 月平均 × (1 + ランダム[-20%, +20%])
推奨発注数量 = max(0, 予測値 + 安全在庫 - 現在庫)
緊急度判定:
在庫≦0 → "緊急"
在庫<安全在庫 → "要注意"
推奨発注>0 → "推奨"
それ以外 → "十分"
AI補完: 月次データ＋商品別予測をAIに渡し、エグゼクティブサマリー＋商品別分析コメントをJSONで生成
5.4.9 アラートチェックサービス（AlertCheckService相当）

各種アラートをデータベースから検出する。

チェック項目:

与信アラート（high）: 与信使用率 95%以上
与信警告（medium）: 与信使用率 80%〜95%
在庫アラート（high）: 在庫 < 安全在庫
在庫切れ（high）: 在庫 ≦ 0
受注滞留（medium）: ステータス"確認中"が3日以上継続

AI分析: 検出されたアラートをAIに渡し、総合分析サマリー＋推奨アクションをJSONで生成。AI分析結果はアラートリストの先頭にseverity:"info"の特別アラートとして挿入。

5.4.10 ワークフローエンジン（WorkflowEngineService相当）

マルチステップワークフローの定義・実行エンジン。

ワークフロー定義:

{
  "id": "wf_demo_stock_alert",
  "name": "在庫アラート通知",
  "enabled": true,
  "trigger": {"type": "schedule", "config": {"intervalMinutes": "30"}},
  "steps": [
    {"order": 1, "name": "在庫レポート生成", "actionType": "report", "config": {"reportType": "stock"}},
    {"order": 2, "name": "在庫切れチェック", "actionType": "condition", "config": {"variable": "step_1_output", "operator": "contains", "value": "在庫切れ"}},
    {"order": 3, "name": "アラート通知", "actionType": "push", "config": {"title": "在庫アラート", "message": "...", "severity": "high"}}
  ]
}


トリガータイプ:

schedule: 一定間隔（分）で実行
screen_navigation: 特定画面遷移時に実行
data_update: 特定テーブルのデータ更新時に実行
manual: 手動実行のみ

アクションタイプ:

ocr: OCR分析を実行（設定: imageBase64, screenType）
search: キーワード検索を実行（設定: keyword, table）
report: レポート生成（設定: reportType=[stock/credit_risk/demand/customer/order], targetId）
auto_input: 自動入力実行（設定: fields JSON, screenType）
push: アラート通知生成（設定: title, message, severity）
recommend: 類似レコード推薦（設定: tableName, recordId, maxResults）
chat: AIチャット実行（設定: systemPrompt, message）
wait: 待機（設定: seconds）
condition: 条件分岐（設定: variable, operator=[equals/contains/not_empty/empty], value）

実行フロー:

有効なワークフローのステップをOrder順に実行
各ステップの出力は step_{order}_output というキーでコンテキストに保存
条件アクションは変数の値に応じて true/false を返す
次のステップへの遷移は nextOnSuccess / nextOnFailure で制御（"next"=次の順序, "end"=終了, 数値=指定オーダーへジャンプ）
全ステップ完了時: status: "completed"、失敗含む場合: status: "failed"

パラメータ解決: {{step_1_output}} の形式でコンテキスト変数を展開

シードデータ: 起動時に4種類のデモワークフローを自動投入

在庫アラート通知: 30分間隔で在庫レポート→在庫切れチェック→プッシュ通知
帳票OCR→自動入力: 受注入力画面遷移時にOCR→自動入力→完了通知
与信超過チェック: 新規受注時（data_update）に与信リスク分析→条件判定→警告通知
日次業務レポート: 毎日8時に在庫/受注/与信レポート→AIサマリー生成→通知
5.4.11 自然言語→SQL変換（QueryService相当）

処理フロー:

システムテーブルスキーマ（全テーブルのカラム一覧）をシステムプロンプトに含める
ユーザーの自然言語クエリをAIに送信
AIが生成したSQLを抽出（````sql ブロック優先）
SQLを検証・実行
実行結果をChart.js互換のグラフデータに変換（可能な場合）
AIサマリーを生成
5.4.12 レポートサービス群（共通パターン）

各レポートサービス（顧客/受注/在庫/仕入先/従業員/見積/請求/利益）は以下の共通パターンに従う：

リクエストパラメータに基づいてDBからデータを取得・集計
集計結果をJSONシリアライズ
集計データをAIに渡し、分析・サマリーをJSONで生成
集計＋AI分析＋グラフデータを含むレスポンスを返却

グラフデータフォーマット（Chart.js互換）:

{
  "type": "bar",  // bar/line/pie/doughnut/radar
  "title": "売上推移",
  "labels": ["1月", "2月", "3月", ...],
  "datasets": [
    {"label": "売上", "data": [100, 150, 120, ...], "backgroundColor": ["#xxx", ...]}
  ]
}

5.4.13 RandomProjectionIndex（ANNインデックス）

ランダム射影による近似最近傍探索（Approximate Nearest Neighbor）の自作実装。

原理: 高次元ベクトルをランダムな低次元部分空間に射影→ハッシュベースのインデックス構築
メソッド:
build(tableName, items: {id, text, embedding}[]): インデックス構築
search(queryVector, topK): 近似最近傍探索→ {index, score} のリスト
getItem(index): 元のアイテム（id, text, embedding）を取得
isBuilt: インデックス構築済みか
save() / load(): 永続化
5.4.14 その他のサービス概要
CompanySearchService: Web検索API（OpenCode CLIのEXA検索またはGoogle Custom Search）を利用した企業情報検索＋結果の構造化
PropertySearchService: 同様に物件情報のWeb検索
CreditRiskService: 与信リスクスコアリング（使用率×滞納実績×取引額の加重スコア）
SalesTrendService: 月次売上推移＋四半期比較＋成長率計算
PurchaseOrderService: 発注CRUD＋AI発注提案＋仕入先評価スコアリング
InventoryService: 在庫トランザクション＋AI分析＋異常検知
ArApService: AR/APエイジング分析（30/60/90日以上区分）
GoodsReceiptService: 入荷管理
AnomalyDetectionService: 統計的異常検知（平均±標準偏差×係数）
AnalysisHistoryService: 分析履歴のCRUD
5.5 設定ファイルの構造
{
  "demoMode": false,           // true=インメモリ, false=DBモード
  "databaseProvider": "SQLite", // "SQLite" / "PostgreSQL" / "SqlServer"
  "connectionStrings": {
    "SQLite": "Data Source=legacy_demo.db",
    "PostgreSQL": "Host=...;Database=...;"
  },
  "jwt": {
    "key": "",                 // 空の場合は認証無効
    "issuer": "LegacyAiApi",
    "audience": "ChromeExtension",
    "expireMinutes": 60
  },
  "aiApi": {
    "apiKey": "",              // OpenAI API Key
    "embeddingModel": "text-embedding-3-small",
    "chatModel": "gpt-4o-mini",
    "maxTokens": 2000
  },
  "gemini": {
    "apiKey": ""               // Gemini API Key
  },
  "embeddingProvider": "e5",   // "e5" / "local" (=OpenAI) / "azure"
  "e5Model": {
    "dimension": 768,
    "timeoutMs": 60000,
    "scriptPath": ""           // 空で自動検出
  },
  "vectorSearch": {
    "dimension": 1536,
    "maxResults": 20,
    "scoreThreshold": 0.2,
    "numTrees": 10,
    "leafSize": 50,
    "sqliteVecDllPath": ""
  },
  "webSearch": {
    "provider": "opencode"     // "opencode" / "google"
  },
  "localCli": {
    "provider": "opencode",    // "opencode" / "gemini" / "ollama"
    "executablePath": "opencode",
    "model": "google/gemma-4-31b-it",
    "timeoutMs": 120000,
    "workDirectory": ""
  },
  "documentProcessing": {
    "maxFileSizeMb": 20,
    "supportedFormats": ["jpg","jpeg","png","pdf","tiff","bmp"],
    "tempDirectory": "TempUploads"
  },
  "systemProfile": {
    "name": "LegacyDemoSystem",
    "displayName": "レガシーシステム デモ",
    "targetOrigin": "http://localhost:5000",
    "tables": {
      "Customers": {
        "label": "顧客", "idColumn": "Id",
        "textColumns": ["Name", "Tel", "Address"],
        "detailUrl": "/Customer/Detail/{id}",
        "searchColumns": ["Name", "Id", "Tel"]
      },
      // ... 同様に Orders, Products, Properties, Suppliers, Employees, Estimates, Invoices, PurchaseOrders
    },
    "screenDetectors": [
      {"pattern": "Order", "titleContains": "受注", "type": "order-input"},
      // ... 全10ルール
    ],
    "autoInputMappings": {
      "会社名": ["CompanyName", "company_name", "Name"],
      // ... 約60エントリ
    },
    "indexTargets": [
      {"table": "Customers", "idColumn": "Id", "textColumns": ["Name", "Tel", "Address"]},
      // ... 全9テーブル
    ]
  }
}

5.6 データモデル（主要DTO）
画面コンテキスト
ScreenContext {
  url: string
  screenType: string
  title: string
  formFields: { [fieldName]: label }
  tableData: [{ [columnName]: value }]
}

ベクトル検索
VectorIndexRequest {
  tableName: string
  idColumn: string
  textColumns: string[]
  whereClause?: string
}
VectorSearchRequest {
  query: string
  tableName?: string
  maxResults?: number (default 10)
  scoreThreshold?: number (default 0)
}
VectorSearchResponse {
  query: string
  results: [{ id: string, text: string, tableName: string, score: float }]
  totalCount: int
  aiSummary?: string
}

検索
SearchRequest {
  keyword?: string
  table?: string
  filters?: { [field]: value }
  conditions?: [{ field, op: "eq"|"ne"|"gt"|"lt"|"ge"|"le"|"contains"|"starts"|"ends", value }]
  orderBy?: { field, direction: "asc"|"desc" }
  page?: number (default 1)
  pageSize?: number (default 20)
}
SearchResponse {
  results: [{ [column]: value }]
  totalCount: int
  page: int
  pageSize: int
  aiSummary?: string
  chart?: ChartData
}

ワークフロー
WorkflowDefinition {
  id: string
  name: string
  description?: string
  enabled: bool
  trigger: { type: "schedule"|"screen_navigation"|"data_update"|"manual", config: { [key]: string } }
  steps: [{ order: int, name: string, actionType: string, config: { [key]: string }, nextOnSuccess?: string, nextOnFailure?: string }]
  createdAt: datetime
  updatedAt: datetime
}
WorkflowExecutionResult {
  workflowId: string
  workflowName: string
  executionId: string
  status: "running"|"completed"|"failed"
  startedAt: datetime
  completedAt?: datetime
  stepResults: [{ order, name, actionType, status, output?, errorMessage?, startedAt, completedAt }]
  errorMessage?: string
}

自動入力
InputMapping {
  fieldName: string
  fieldValue: string
  confidence: "high"|"medium"
  selector: string   // CSS selector
}
ParsedIntent {
  action: string
  fields: { [label]: value }
  lineItems: [{ productName?, productCode?, quantity?, unitPrice?, amount? }]
  screenType?: string
  targetCustomer?: string
  targetProduct?: string
}
ConversationalInputResponse {
  response: string
  conversationId: string
  inputMappings: InputMapping[]
  intent: ParsedIntent
  missingFields: string[]
  confidence: "high"|"medium"|"low"
}

アラート
AlertInfo {
  type: "credit"|"stock"|"order"|"workflow"|"alert"
  severity: "high"|"medium"|"info"
  title: string
  message: string
  targetId?: string
  targetUrl?: string
  detectedAt: datetime
}
AlertCheckResponse {
  alerts: AlertInfo[]
  totalAlerts: int
  highCount: int
  mediumCount: int
  aiAnalysis?: string
}

需要予測
ProductDemandForecast {
  productId: string
  productName: string
  category: string
  unitPrice: decimal
  currentStock: int
  safetyStock: int
  historicalMonthlyAvg: int
  predictedDemandNextMonth: int
  suggestedOrderQuantity: int
  urgency: "緊急"|"要注意"|"推奨"|"十分"
  aiAnalysis?: string
  recommendations?: string[]
}

6. デモレガシーシステム（Demo Legacy System）実装仕様
6.1 概要

これは模擬的なWebForms風ERPシステムであり、実際のレガシーシステムを模倣するためのデモ用Webアプリケーションである。このシステム自体にAI機能は一切なく、Chrome拡張機能をテスト・デモンストレーションするためのターゲットとなる。

6.2 技術要件（言語非依存）

任意のWebフレームワークで実装可能。以下の要件を満たせばよい：

サーバーサイドHTMLレンダリング（SPAではなく、ページ遷移型）
フォームベースのCRUD画面（伝統的なWebフォーム）
グリッドレイアウトの一覧画面
画面タイトルに日本語を含む
ポート5000で動作

推奨実装例：

Python: Flask + Jinja2, Django
Node.js: Express + EJS/Pug
Go: Gin + html/template
Java: Spring Boot + Thymeleaf
.NET: ASP.NET Core MVC + Razor
6.3 画面一覧と画面構成

全13のビジネスエンティティに対応するコントローラ＋画面を持つ。各エンティティは以下の画面タイプを持つ：

エンティティ	一覧画面	登録/編集画面	詳細画面	検索画面
Home（ダッシュボード）	Index (メインメニュー)	—	—	—
Customer（顧客）	List	Entry	Detail	Search
Order（受注）	List	Entry	Detail	—
Product/Stock（商品/在庫）	—	—	Inquiry	—
Supplier（仕入先）	List	Entry	Detail	—
Employee（従業員）	List	Entry	Detail	—
Estimate（見積）	List	Entry	Detail	—
Invoice（請求）	List	Entry	Detail	—
PurchaseOrder（発注）	List	Entry	Detail	—
InventoryTransaction（在庫トランザクション）	List	—	—	—
GoodsReceipt（入荷）	List	Entry	—	—
Property（物件）	List	Entry	Detail	Register
ArAp（売掛買掛）	List	—	—	—
Profit（利益）	List	—	—	—
Stock（在庫照会）	—	—	Inquiry	—
6.4 ルーティング定義
メソッド	パス	説明
GET	/	トップページ（ダッシュボード＋メインメニュー）
GET	/{entity}/List	一覧画面（テーブル表示＋ページネーション）
GET	/{entity}/Entry	新規登録画面（空のフォーム）
GET	/{entity}/Entry/{id}	編集画面（既存データをフォームにセット）
POST	/{entity}/Entry	登録/更新処理
GET	/{entity}/Detail/{id}	詳細画面（読み取り専用）
GET	/{entity}/Search	検索画面（条件入力→結果表示）
POST	/{entity}/Search	検索処理

※ エンティティごとに利用可能な画面は異なる（上記一覧参照）

6.5 個別画面の実装詳細
6.5.1 共通レイアウト
上部: ナビゲーションバー（システムタイトル＋メニューリンク）
メイン: 各画面のコンテンツ（幅1200px程度のコンテナ）
画面タイトル: 日本語で表示（例：「顧客管理」「受注入力」「在庫照会」）
6.5.2 Home/Index（ダッシュボード）
システムタイトル表示
各機能へのリンクボタン（顧客管理、受注管理、商品在庫、仕入先管理、等）
簡易サマリー情報（顧客数、受注数、在庫数等）
6.5.3 Customer（顧客管理）
一覧（List）: テーブル（ID, 会社名, TEL, 住所, 与信限度額, 与信使用率）
各行に編集・詳細リンク
新規登録ボタン
登録/編集（Entry）: フォーム（会社名, カナ, 代表者, 郵便番号, 住所, TEL, FAX, Webサイト, 資本金, 従業員数, 業種, 与信限度額, 備考）
フォーム項目はinput/textarea/select
「登録」「更新」「戻る」ボタン
詳細（Detail）: 全項目の読み取り専用表示
検索（Search）: キーワード入力＋テーブル結果表示
6.5.4 Order（受注管理） - 最も重要な画面
一覧（List）: テーブル（受注ID, 顧客名, 受注日, 納期, 合計金額, ステータス, 備考）
登録/編集（Entry） ※受注入力画面 = order-input:
ヘッダー部: 顧客ドロップダウン（select[name="customerId"]）、受注日（input[name="orderDate"]）、納期（input[name="deliveryDate"]）、備考（textarea[name="notes"]）
明細行グリッド: <table id="item-table"> + <tbody id="item-table-body">
各行: 商品ドロップダウン（select[name="productId"] / optionのdata-price属性に単価）、数量（input[name="quantity"] / class="qty-input"）、単価表示（.price-input）、金額セル（.amount-cell）、削除ボタン
「行追加」ボタン（addItem() 関数、JavaScriptで動的追加）
数量変更時に自動金額計算＋合計更新（#order-total）
合計表示: #order-total
JavaScript関数: addItem(), recalcTotal()
addItem(): <script> タグ内にインライン実装。商品選択肢のHTMLを含む
詳細（Detail）: ヘッダー情報＋明細行テーブル
6.5.5 Product/Stock（商品管理）
照会（Inquiry）: 商品一覧テーブル（ID, 商品名, カテゴリ, 単価, 在庫数, 安全在庫）
6.5.6 Supplier（仕入先管理）
一覧（List）: テーブル（ID, 仕入先名, カテゴリ, TEL, 担当者, 与信枠）
登録/編集（Entry）: フォーム（仕入先名, カテゴリ, TEL, 住所, 担当者, 与信枠, 支払条件, 備考）
詳細（Detail）: 全項目表示
6.5.7 Employee（従業員管理）
一覧（List）: テーブル（ID, 氏名, 部署, 役職, メール, TEL）
登録/編集（Entry）: フォーム（氏名, 部署, 役職, メール, TEL, 入社日）
詳細（Detail）: 全項目表示
6.5.8 Estimate（見積管理）
一覧（List）: テーブル（見積番号, 顧客名, 見積日, 有効期限, 合計金額, ステータス）
登録/編集（Entry）: 顧客ドロップダウン（select[name="customerId"]）、見積日（input[name="estimateDate"]）、有効期限（input[name="validUntil"]）、明細行グリッド（Order同様）、合計（#estimate-total）
6.5.9 Invoice（請求管理）
一覧（List）: テーブル（請求番号, 顧客名, 請求日, 支払期日, 金額, ステータス）
登録/編集（Entry）: フォーム（顧客, 請求日, 支払期日, 金額, 関連受注, 備考）
6.5.10 PurchaseOrder（発注管理）
一覧（List）: テーブル（発注番号, 仕入先, 発注日, 納期, 合計金額, ステータス）
登録/編集（Entry）: フォーム（仕入先, 発注日, 納期, 明細）
6.5.11 Property（物件管理）
一覧（List）: テーブル（物件名, 住所, 価格, 築年月）
登録/編集（Entry）: フォーム（物件名, フリガナ, 住所, 交通, 敷地面積, 建物面積, 構造, 階数, 築年月, 権利形態, 取引形態, 価格, 月額賃料, 設備）
新規登録（Register）: Entryとほぼ同様（/Property/Register という別URL）
詳細（Detail）: 全項目表示
6.5.12 その他の画面
InventoryTransaction（在庫トランザクション）: 一覧のみ（商品, 種別, 数量, 日付, 備考）
GoodsReceipt（入荷管理）: 一覧＋登録（仕入先, 商品, 数量, 入荷日）
ArAp（売掛買掛）: 一覧（顧客/仕入先別の売掛金/買掛金残高）
Profit（利益管理）: 一覧（商品別売上/原価/粗利/粗利率）
6.6 画面タイトル命名規則

各画面の <title> と画面上の見出しは日本語で設定する：

画面	タイトル
顧客一覧	"顧客管理" または "顧客一覧"
顧客登録	"顧客新規登録"
顧客詳細	"顧客詳細"
受注一覧	"受注管理" または "受注一覧"
受注入力	"受注入力"
在庫照会	"在庫照会"
仕入先一覧	"仕入先一覧"
従業員一覧	"従業員一覧"
見積一覧	"見積一覧"
請求一覧	"請求一覧"
発注一覧	"発注一覧"
物件一覧	"物件一覧"
物件登録	"物件新規登録"
6.7 データアクセス
6.7.1 データ保持方式

デモシステムは AI APIサーバーと同一のデータを共有 する。推奨方式：

方式A（簡易）: 静的インメモリデータストア（Singleton/グローバル変数）をAPIサーバーと共有
方式B（独立）: 各システムが独立したSQLiteデータベースを持ち、同じダミーデータを保持
方式C（API経由）: デモシステム自身はデータを持たず、APIサーバーのCRUDエンドポイントを呼び出す
6.7.2 ダミーデータ

全エンティティに以下のようなダミーデータを用意する：

顧客: 10〜20件（会社名、住所、TEL、与信限度額等）
商品: 10〜20件（カテゴリ別、単価、在庫数、安全在庫）
受注: 30〜50件（様々な日付・ステータス・金額）
仕入先: 5〜10件
従業員: 10〜15件
見積/請求/発注: 各10〜20件
物件: 5〜10件
在庫トランザクション: 30〜50件
AR/APデータ: 顧客/仕入先別残高
6.8 UIスタイル
CSSは public/css/site.css に記述（素のCSS、フレームワーク不要）
JavaScriptは public/js/site.js に記述（素のJS、jQuery不要だが使用可）
テーブル: 標準的なHTMLテーブル（<table><thead><tr><th>...</th></tr></thead><tbody>...</tbody></table>）
フォーム: テーブルベースレイアウト（<table class="form-table"><tr><th>ラベル</th><td>入力欄</td></tr>...</table>）
入力欄: <input type="text" class="textbox" name="xxx" id="xxx">
数値: <input type="number" class="textbox num" name="xxx">
ドロップダウン: <select name="xxx">
ボタン: <input type="submit" class="button" value="..."> / <button type="button" class="button small">
リンクボタン風: <a href="..." class="button-link">
7. DBスキーマ（本番モード用）
7.1 業務テーブル
CREATE TABLE Customers (
    Id TEXT PRIMARY KEY,
    Name TEXT NOT NULL,
    NameKana TEXT,
    Tel TEXT,
    Address TEXT,
    PostalCode TEXT,
    Representative TEXT,
    CreditLimit DECIMAL(12,0) DEFAULT 0,
    CreditUsed DECIMAL(12,0) DEFAULT 0,
    LastPayment TEXT,
    Notes TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Orders (
    Id TEXT PRIMARY KEY,
    CustomerId TEXT,
    CustomerName TEXT,
    OrderDate TEXT,
    DeliveryDate TEXT,
    TotalAmount DECIMAL(12,0) DEFAULT 0,
    Status TEXT DEFAULT '確認中',
    Notes TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

-- OrderItems（受注明細）
CREATE TABLE OrderItems (
    Id INTEGER PRIMARY KEY AUTOINCREMENT,
    OrderId TEXT NOT NULL,
    ProductId TEXT,
    ProductName TEXT,
    Quantity INTEGER DEFAULT 1,
    UnitPrice DECIMAL(10,0) DEFAULT 0,
    Amount DECIMAL(12,0) DEFAULT 0,
    FOREIGN KEY (OrderId) REFERENCES Orders(Id)
);

CREATE TABLE Products (
    Id TEXT PRIMARY KEY,
    Name TEXT NOT NULL,
    Category TEXT,
    UnitPrice DECIMAL(10,0) DEFAULT 0,
    Stock INTEGER DEFAULT 0,
    SafetyStock INTEGER DEFAULT 0
);

CREATE TABLE Suppliers (
    Id TEXT PRIMARY KEY,
    Name TEXT NOT NULL,
    Category TEXT,
    Tel TEXT,
    Address TEXT,
    ContactPerson TEXT,
    CreditAmount DECIMAL(12,0) DEFAULT 0,
    PaymentTerms TEXT,
    Notes TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Employees (
    Id TEXT PRIMARY KEY,
    Name TEXT NOT NULL,
    Department TEXT,
    Position TEXT,
    Email TEXT,
    Tel TEXT,
    HireDate TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Properties (
    Id TEXT PRIMARY KEY,
    Name TEXT NOT NULL,
    NameKana TEXT,
    Address TEXT,
    Access TEXT,
    LandArea DECIMAL(10,2),
    BuildingArea DECIMAL(10,2),
    Structure TEXT,
    Floors INTEGER,
    BuiltDate TEXT,
    LandRight TEXT,
    TransactionType TEXT,
    Price DECIMAL(14,0),
    MonthlyRent DECIMAL(10,0),
    OccupancyRate DECIMAL(5,2),
    ParkingSpaces INTEGER,
    Facilities TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Estimates (
    Id TEXT PRIMARY KEY,
    CustomerId TEXT,
    CustomerName TEXT,
    EstimateDate TEXT,
    ValidUntil TEXT,
    TotalAmount DECIMAL(12,0) DEFAULT 0,
    Status TEXT DEFAULT '作成中',
    Notes TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE Invoices (
    Id TEXT PRIMARY KEY,
    CustomerId TEXT,
    CustomerName TEXT,
    InvoiceDate TEXT,
    DueDate TEXT,
    TotalAmount DECIMAL(12,0) DEFAULT 0,
    Status TEXT DEFAULT '未払い',
    OrderId TEXT,
    Notes TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE PurchaseOrders (
    Id TEXT PRIMARY KEY,
    SupplierId TEXT,
    SupplierName TEXT,
    OrderDate TEXT,
    DeliveryDate TEXT,
    TotalAmount DECIMAL(12,0) DEFAULT 0,
    Status TEXT DEFAULT '発注中',
    Notes TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

7.2 システムテーブル
CREATE TABLE VectorCache (
    Id TEXT,
    TableName TEXT,
    OriginalText TEXT,
    EmbeddingJson TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (Id, TableName)
);

CREATE TABLE PushSubscriptions (
    Id TEXT PRIMARY KEY,
    Endpoint TEXT NOT NULL,
    P256Dh TEXT,
    Auth TEXT,
    DeviceName TEXT,
    CreatedAt TEXT DEFAULT CURRENT_TIMESTAMP
);

-- sqlite-vec 仮想テーブル（動的作成、名前 = vec_{TableName}）
-- CREATE VIRTUAL TABLE vec_Customers USING vec0(id TEXT PRIMARY KEY, embedding float[768]);

8. 注目すべき実装パターン（言語非依存）
8.1 デモ/本番デュアルモード

全サービスのコンストラクタで設定ファイルの demoMode を読み取り、以下のように分岐：

if (isDemo):
    // インメモリデータストアを使用（DB不要）
else:
    // 実際のデータベースを使用
    // JWT認証を有効化（設定により）


コントローラはモードを意識せず、サービス内で透過的に処理される。

8.2 マルチプロバイダAI抽象化

AIクライアントは以下のプロバイダを透過的に切り替える：

aiClient = AiHttpClient(config)
// 内部的に provider によって分岐:
//   "opencode" → OpenCodeCLIService
//   "gemini"   → GeminiAPI
//   それ以外   → OpenAI API


埋め込みも同様：

// AI APIが利用可能 → AI API経由（高品質）
// AI APIが不可 → LocalEmbeddingService（E5）
// E5も不可 → n-gramフォールバック（簡易だが常に動作）

8.3 3層ベクトル検索

優先順位に従って検索方式を自動選択：

searchMethod = resolveMethod(tableName)
switch searchMethod:
    case "sqlite-vec":    return searchSqliteVec(query)     // 最速、DLL要
    case "random-projection": return searchAnn(query)        // 中速、純粋実装
    case "brute-force":   return searchBruteForce(query)     // 低速、常に利用可


各方式の出力は同じ形式で統一され、呼び出し元は方式を意識しない。

8.4 拡張可能なプロファイル設計

Chrome拡張機能はプロファイルベースで複数システムに対応：

chrome-extension/
  profiles/
    template/           ← 新規システム用テンプレート（コピーして使用）
    legacy-demo/        ← 既存のデモシステム用プロファイル
    customer-a/         ← 将来的に追加可能


プロファイルには以下を含む：

システム固有のURL設定
画面検出ルール
類義語マッピング
詳細リンク解決ロジック
8.5 Shadow DOM完全分離

Chrome拡張機能は mode: 'closed' のShadow DOMを使用してホストページから完全隔離：

host = createElement('div')
host.id = 'ai-assistant-root'
shadow = host.attachShadow({ mode: 'closed' })
shadow.innerHTML = CSS + HTML
body.appendChild(host)


CSS変数（--sidebar-w）で動的な幅制御を実現。

8.6 AIとのJSON通信パターン

LLMとの構造化データのやり取りは以下の方式：

プロンプト内でJSONスキーマを指定: AIに出力フォーマットを明示
レスポンスからJSON抽出: 正規表現で ````json ` ブロックを抽出、または全文をパース試行
JSON検証: パースに失敗した場合のフォールバック処理
グラフデータ変換: 検索結果や集計データをChart.js互換のJSON形式に変換
9. 実装の優先順位

段階的に実装する場合の推奨順序：

Phase 1: 最小構成（1〜2日）
Chrome拡張機能の基本構造（shared/ + profile + content-script + sidebar）
AI APIサーバーの基本構成（エントリポイント + ルーティング + 設定）
デモレガシーシステムの基本画面（Home + Customer CRUD）
DocumentController + OcrAnalysisService（OCR機能）
LocalAiController（チャット機能）
Phase 2: 検索・レポート（2〜3日）
VectorController + EmbeddingService（ベクトルインデックス）
SearchController + SearchService（キーワード・横断検索）
QueryController + QueryService（自然言語→SQL）
全レポートサービス + コントローラ
デモレガシーシステムの全画面実装
Phase 3: 予測・ワークフロー（2〜3日）
ForecastController + DemandForecastService
WorkflowController + WorkflowEngineService
ConversationalInputController + ConversationalInputService
BusinessAssistantService
全パネルモジュールの完成
Phase 4: 管理・通知・拡張（1〜2日）
PushController + AlertCheckService
PurchaseOrderController + InventoryController
ProfitReportController + ArApController
デモデータ充実
テスト・調整
10. 注意点・ベストプラクティス（言語非依存）
コメント: 日本語コメントで実装意図を明確に記述（他のAI開発者が理解できるように）。クラス・メソッドの先頭に役割と引数・戻り値の説明を必ず書く
エラーハンドリング: 各サービスは内部で例外をキャッチし、上位にRAWの例外を伝播しない。想定されるエラーケースをすべて考慮
非同期処理: 全AI呼び出し・DB操作はイベントループ/非同期APIを使用（スレッドブロック回避）
スレッドセーフ: 静的キャッシュ/シングルトンはスレッドセーフなデータ構造（ConcurrentHashMap等）で保護
設定駆動: ハードコード値を避け、設定ファイルからの読み込みを徹底。環境変数での上書きも考慮
デモデータ: デモモードでは実際のDB操作をせず、インメモリで完結。起動が高速で環境依存がゼロ
JSONシリアライズ: 全APIレスポンスは camelCase のJSON形式で統一
ベクトル演算: float配列のコサイン類似度計算は頻繁に呼ばれるため、パフォーマンスに注意（SIMD最適化が可能なら検討）
CLIプロセス管理: 外部CLIプロセスは確実にタイムアウト処理を行い、リソースリークを防止。一時ファイルは必ず削除
デモシステムの画面タイトル: Chrome拡張機能の画面検出はURLパターンと画面タイトルの両方を見る。タイトルに日本語を含めること
フォームフィールド名: Chrome拡張機能の自動入力はフィールド名（name属性）をキーにする。一貫性のある命名を守る