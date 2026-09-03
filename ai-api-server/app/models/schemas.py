"""Pydantic スキーマ定義（言語非依存仕様の Models 層）"""
from datetime import datetime
from typing import Any
from pydantic import BaseModel, Field


# ---------- Customer ----------
class CustomerBase(BaseModel):
    name: str
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    notes: str | None = None
    status: str | None = None  # 例: 取引中 / 休止 (ワークフロー条件で参照)


class CustomerCreate(CustomerBase):
    pass


class CustomerUpdate(BaseModel):
    name: str | None = None
    email: str | None = None
    phone: str | None = None
    company: str | None = None
    notes: str | None = None
    status: str | None = None


class Customer(CustomerBase):
    id: int
    created_at: datetime
    updated_at: datetime


# ---------- Order ----------
class OrderBase(BaseModel):
    customer_id: int
    item: str
    qty: int
    amount: float
    date: str  # ISO日付 "YYYY-MM-DD"


class OrderCreate(OrderBase):
    pass


class Order(OrderBase):
    id: int


# ---------- Chat ----------
class ChatMessage(BaseModel):
    role: str  # user | assistant | system
    content: str


class ChatRequest(BaseModel):
    session_id: str = Field(default="default")
    message: str


class ChatResponse(BaseModel):
    session_id: str
    reply: str
    provider: str
    history_length: int


# ---------- OCR ----------
class OcrResult(BaseModel):
    filename: str
    extracted_text: str
    fields: dict[str, str]
    confidence: float
    source: str = "mock"


class OcrRegisterRequest(BaseModel):
    fields: dict  # OcrResult.fields をそのまま渡す想定
    entity: str  # "Customer" | "Supplier" | "Employee" | "Property"(erpのみ)


class OcrRegisterResponse(BaseModel):
    success: bool
    normalized: dict  # レガシーフォームのフィールド名(Name/Tel/...)に正規化済み
    entry_entity: str


class OcrEntitiesResponse(BaseModel):
    entities: list[str]  # この業態(instance)でOCR自動入力先として選べるエンティティ名一覧


# ---------- Search ----------
class SearchRequest(BaseModel):
    query: str
    top_k: int = 5


class SearchHit(BaseModel):
    id: int
    type: str
    title: str
    snippet: str
    score: float


class SearchResponse(BaseModel):
    query: str
    backend: str
    results: list[SearchHit]


# ---------- Predictive Analytics ----------
class ForecastPoint(BaseModel):
    month: str  # "YYYY-MM"
    actual: float | None = None  # 未来月は None（predicted のみ）
    predicted: float


class ForecastResponse(BaseModel):
    method: str
    history_months: int
    forecast_months: int
    points: list[ForecastPoint]


class ReorderPrediction(BaseModel):
    customer_id: int
    customer_name: str
    last_order_date: str
    avg_interval_days: float
    expected_next_date: str
    days_until_expected: int
    risk: str  # overdue | due_soon | on_track


class PredictionResponse(BaseModel):
    generated_at: datetime
    predictions: list[ReorderPrediction]


# ---------- AI Insight (統計/ルール結果 -> AIによる解釈コメント) ----------
class InsightResponse(BaseModel):
    comment: str
    provider: str  # 生成に使ったAiProvider名(mock|opencode|openai|gemini)


# ---------- 自然言語 → 構造化フィルタ検索 (5.4.11 差分実装) ----------
# 仕様書5.4.11は「AIが生成したSQLを直接実行する」方式を規定しているが、データ層が
# 実SQLエンジンを持たないインメモリdict(demo-legacy-system/data.py)であることに加え、
# インジェクション/誤操作のリスクを本質的に断つため、AIには構造化フィルタ(JSON)のみを
# 生成させ、ホワイトリスト検証を通過した条件だけをコード側で評価する(evalも生SQLも使わない)。
class NLSQLQueryRequest(BaseModel):
    entity: str
    question: str


class NLSQLCondition(BaseModel):
    field: str
    op: str  # eq|ne|gt|gte|lt|lte|contains|in
    value: str | float | int | bool | list | None = None


class NLSQLFilter(BaseModel):
    conditions: list[NLSQLCondition] = []
    logic: str = "and"  # and|or
    sort: dict | None = None  # {"field": ..., "dir": "asc"|"desc"}
    limit: int = 50


class NLSQLQueryResponse(BaseModel):
    entity: str
    label: str
    question: str
    applied_filter: NLSQLFilter
    # 表示専用の疑似SQL(実行はしない。データ層に実SQLエンジンは存在しない。
    # applied_filterを人間が読みやすいSQL風に機械的に整形しただけの透明性表示。
    # 詳細は filter_ops.render_condition_sql / nlsql_service._build_sql_preview 参照)
    sql_preview: str
    warnings: list[str] = []
    total_scanned: int
    count: int
    rows: list[dict]
    provider: str


# ---------- クロス分析(複数エンティティを跨いだ集計・分析 + チャート) ----------
# nlsql(単一エンティティの自然文フィルタ)では表現できない「与信リスク」
# 「在庫逼迫」「滞留債権」等、複数エンティティの突き合わせが必要な定型レポート。
# 算出ロジック自体はAI非依存(cross_analysis_service.py参照)。
class CrossAnalysisReportMeta(BaseModel):
    id: str
    label: str
    unit: str


class ChartSeries(BaseModel):
    label: str
    values: list[float | int | None]


class ChartData(BaseModel):
    type: str  # ranked-bar | ranked-bar-grouped | trend-line
    unit: str
    categories: list[str]
    series: list[ChartSeries]


# 棒グラフ(ranked-bar/-grouped)だけでは「内訳(part-to-whole)」が読み取りにくいため、
# 与信リスク/在庫逼迫/滞留債権のような状態分類は積み上げ横棒(構成比)でも表現する。
# statusは既存の .aisb-risk-* 配色(good=正常/warning=警戒/critical=超過等)と揃える。
class DistributionSlice(BaseModel):
    label: str
    count: int
    status: str  # good | warning | critical


class DistributionData(BaseModel):
    title: str
    slices: list[DistributionSlice]


class CrossAnalysisResponse(BaseModel):
    report: str
    label: str
    generated_at: datetime
    summary: dict
    chart: ChartData
    distribution: DistributionData | None = None
    rows: list[dict]
    warnings: list[str] = []


# ---------- AI自動生成クロス分析(汎用集計エンジン) ----------
# cross_analysis_service.py の3レポートはハードコードされた専用ロジックだが、
# こちらはAIが「主エンティティ/副エンティティ/JOIN/GROUP BY/集計方法」を
# 構造化パラメータ(JSON)として生成し、JOIN_GRAPH(dynamic_analysis_service.py)で
# 固定された安全な結合キーのみを使って実行する汎用版。生SQL/evalは使わない。
class DynamicAnalysisRequest(BaseModel):
    question: str


class DynamicAnalysisFieldRef(BaseModel):
    scope: str  # primary|secondary
    field: str


class DynamicAnalysisFilter(DynamicAnalysisFieldRef):
    op: str  # eq|ne|gt|gte|lt|lte|contains|in
    value: str | float | int | bool | list | None = None


class DynamicAnalysisSpec(BaseModel):
    primary_entity: str
    secondary_entity: str | None = None
    filters: list[DynamicAnalysisFilter] = []
    group_by: DynamicAnalysisFieldRef | None = None
    metric: DynamicAnalysisFieldRef | None = None
    agg: str = "count"  # sum|count|avg|min|max
    sort_dir: str = "desc"
    limit: int = 15
    chart_label: str = "集計結果"


class DynamicAnalysisResponse(BaseModel):
    report: str = "generated"
    label: str
    question: str
    spec: DynamicAnalysisSpec | None = None
    # 表示専用の疑似SQL(実行はしない。specから機械的に整形しただけの透明性表示。
    # 詳細は dynamic_analysis_service._build_sql_preview 参照)。spec同様、解釈失敗時はNone。
    sql_preview: str | None = None
    generated_at: datetime
    summary: dict
    chart: ChartData
    rows: list[dict]
    warnings: list[str] = []
    provider: str


# ---------- Workflow Engine (マルチステップ・パイプライン, README 5.4.10) ----------
class WorkflowTrigger(BaseModel):
    type: str  # schedule | screen_navigation | data_update | manual
    config: dict = {}


class WorkflowStep(BaseModel):
    order: int
    name: str
    action_type: str  # ocr|search|report|auto_input|push|recommend|chat|wait|condition
    config: dict = {}
    next_on_success: str | int | None = None  # "next" | "end" | 数値(オーダー番号へジャンプ)
    next_on_failure: str | int | None = None


class WorkflowDefinitionCreate(BaseModel):
    name: str
    description: str | None = None
    enabled: bool = True
    trigger: WorkflowTrigger
    steps: list[WorkflowStep]


class WorkflowDefinitionUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    enabled: bool | None = None
    trigger: WorkflowTrigger | None = None
    steps: list[WorkflowStep] | None = None


class WorkflowDefinition(BaseModel):
    id: str
    name: str
    description: str | None = None
    enabled: bool
    trigger: WorkflowTrigger
    steps: list[WorkflowStep]
    created_at: datetime
    updated_at: datetime


class WorkflowToggleResult(BaseModel):
    id: str
    enabled: bool


class WorkflowTriggerEvalRequest(BaseModel):
    current_screen_type: str | None = None
    changed_table: str | None = None


class WorkflowTriggerEvalResult(BaseModel):
    matched_workflows: list[WorkflowDefinition]


class WorkflowExecuteRequest(BaseModel):
    context: dict = {}


class WorkflowStepResult(BaseModel):
    order: int
    name: str
    action_type: str
    status: str  # success | failed
    output: Any = None
    error: str | None = None


class WorkflowExecutionResult(BaseModel):
    id: int
    workflow_id: str
    workflow_name: str
    trigger_type: str
    status: str  # completed | failed
    started_at: datetime
    finished_at: datetime
    steps: list[WorkflowStepResult]
    context: dict


# ---------- Notifications ----------
class Notification(BaseModel):
    id: int
    source: str  # workflow | admin | system | manual
    level: str  # info | warning | critical
    title: str
    message: str
    ref_type: str | None = None
    ref_id: int | None = None
    read: bool
    created_at: datetime


class NotificationCreate(BaseModel):
    source: str = "manual"
    level: str = "info"
    title: str
    message: str
    ref_type: str | None = None
    ref_id: int | None = None


class NotificationMarkResult(BaseModel):
    marked: int


# ---------- Inventory / Product (Phase4: README 9章「InventoryController」) ----------
class ProductBase(BaseModel):
    name: str
    sku: str
    stock: int
    reorder_point: int  # これを下回ると異常検知(anomalies)で検出される
    unit_cost: float
    supplier: str


class ProductCreate(ProductBase):
    pass


class ProductUpdate(BaseModel):
    name: str | None = None
    sku: str | None = None
    stock: int | None = None
    reorder_point: int | None = None
    unit_cost: float | None = None
    supplier: str | None = None


class Product(ProductBase):
    id: int


class InventoryAnomaly(BaseModel):
    product_id: int
    product_name: str
    stock: int
    reorder_point: int
    shortage: int  # reorder_point - stock (正の値のみ異常)
    severity: str  # warning | critical (stock==0はcritical)


class InventoryAnomalyResponse(BaseModel):
    generated_at: datetime
    anomalies: list[InventoryAnomaly]


# ---------- Purchase Order (Phase4: README 9章「PurchaseOrderController」) ----------
class PurchaseOrderBase(BaseModel):
    product_id: int
    supplier: str
    qty: int
    status: str = "ordered"  # ordered | received | cancelled
    ordered_at: str
    expected_date: str | None = None
    received_qty: int = 0


class PurchaseOrderCreate(BaseModel):
    product_id: int
    supplier: str
    qty: int
    expected_date: str | None = None


class PurchaseOrder(PurchaseOrderBase):
    id: int


class PurchaseOrderProposal(BaseModel):
    product_id: int
    product_name: str
    current_stock: int
    reorder_point: int
    suggested_qty: int
    supplier: str
    reason: str  # 提案根拠(在庫僅少/reorder_point割れ 等の説明文)


class PurchaseOrderProposalResponse(BaseModel):
    generated_at: datetime
    proposals: list[PurchaseOrderProposal]


class GoodsReceiptRequest(BaseModel):
    purchase_order_id: int
    received_qty: int


class SupplierEvaluation(BaseModel):
    supplier: str
    order_count: int
    total_qty: int
    on_time_rate: float  # received済みPOのうちexpected_date以内に揃った割合
    rating: str  # good | normal | caution


class SupplierEvaluationResponse(BaseModel):
    generated_at: datetime
    evaluations: list[SupplierEvaluation]


# ---------- Profit Report (Phase4: README 9章「ProfitReportController」) ----------
class ProfitDataPoint(BaseModel):
    product_name: str
    revenue: float
    profit: float


class ProductProfitDetail(BaseModel):
    product_name: str
    qty: int
    revenue: float
    cost: float
    profit: float
    margin_rate: float  # profit / revenue (revenue==0 の場合は0)
    cost_known: bool  # False = 商品マスタに原価未登録(costは0扱い、参考値)


class ProfitReportResponse(BaseModel):
    generated_at: datetime
    period: str | None = None  # "YYYY-MM" 絞り込み条件(未指定なら全期間)
    profit_data: list[ProfitDataPoint]
    product_details: list[ProductProfitDetail]
    total_profit: float
    summary: str  # ルールベース集計コメント(AIではない。AI解釈が欲しい場合は /insight を叩く)


# ---------- AR/AP Aging (Phase4: README 9章「ArApController」) ----------
class AgingEntry(BaseModel):
    entity_type: str  # receivable(売掛) | payable(買掛)
    entity_name: str  # 顧客名 or 仕入先名
    current: float  # 未到来(期日前)
    bucket_1_30: float
    bucket_31_60: float
    bucket_61_90: float
    bucket_90_plus: float
    total: float
    risk: str  # low | medium | high


class ArApAgingResponse(BaseModel):
    generated_at: datetime
    aging_report: list[AgingEntry]
    total_receivable: float
    total_payable: float
    summary: str  # ルールベース集計コメント(AIではない。AI解釈が欲しい場合は /insight を叩く)


# ---------- Admin ----------
class AdminStats(BaseModel):
    demo_mode: bool
    ai_provider: str
    vector_backend: str
    customer_count: int
    order_count: int
    workflow_count: int
    workflow_execution_count: int
    unread_notification_count: int
    generated_at: datetime


class AuditLogEntry(BaseModel):
    id: int
    actor: str
    action: str
    detail: str
    at: datetime


# ---------- Push Notification (Phase4: README 9章「PushController + AlertCheckService」) ----------
class PushSubscriptionCreate(BaseModel):
    endpoint: str
    p256dh: str | None = None
    auth: str | None = None
    device_name: str | None = None


class PushUnsubscribeRequest(BaseModel):
    endpoint: str


class PushSubscription(BaseModel):
    id: int
    endpoint: str
    p256dh: str | None = None
    auth: str | None = None
    device_name: str | None = None
    created_at: datetime


class PushSubscribeResult(BaseModel):
    success: bool


class PushAlert(BaseModel):
    source: str  # inventory | ar_ap
    severity: str  # high | medium | info (README 5.1: high=赤, medium=黄, info=青)
    title: str
    message: str
    ref_type: str | None = None
    ref_id: int | None = None


class PushCheckResponse(BaseModel):
    generated_at: datetime
    alerts: list[PushAlert]
    total_alerts: int
    high_count: int
    medium_count: int
    summary: str | None = None  # ルールベース集計コメント(AIではない。AI解釈が欲しい場合は /insight を叩く)


# ---------- Analysis History (Phase4: README 9章「AnalysisHistoryService」) ----------
class AnalysisHistoryCreate(BaseModel):
    type: str
    query: str
    result: dict


class AnalysisHistoryEntry(BaseModel):
    id: int
    type: str
    query: str
    result: dict
    created_at: datetime


# ---------- Web Search: Company / Property (Phase2: README 5.3節「外部データ検索系」) ----------
class CompanySearchRequest(BaseModel):
    keyword: str


class CompanySearchResult(BaseModel):
    name: str
    name_kana: str | None = None
    representative: str | None = None
    address: str | None = None
    tel: str | None = None
    website: str | None = None
    industry: str | None = None
    capital: int | None = None
    employees: int | None = None


class CompanySearchResponse(BaseModel):
    keyword: str
    results: list[CompanySearchResult]
    source: str | None = None  # "opencode-websearch"(実検索) | "mock"(擬似データ)


class CompanyRegisterRequest(BaseModel):
    company_data: dict


class CompanyRegisterResponse(BaseModel):
    success: bool
    normalized: dict  # レガシーフォームのフィールド名(Name/NameKana/...)に正規化済み
    # 自動入力先エンティティ(erp="Customer", dealer="Supplier")。
    # フロント側で instance からの再導出をせずに済むよう、サーバー側の判断をそのまま渡す。
    entry_entity: str = "Customer"


class PropertySearchRequest(BaseModel):
    keyword: str


class PropertySearchResult(BaseModel):
    name: str
    name_kana: str | None = None
    address: str | None = None
    access: str | None = None
    land_area: float | None = None
    building_area: float | None = None
    structure: str | None = None
    floors: int | None = None
    built_date: str | None = None
    price: int | None = None
    monthly_rent: int | None = None


class PropertySearchResponse(BaseModel):
    keyword: str
    results: list[PropertySearchResult]
    source: str | None = None  # "opencode-websearch"(実検索) | "mock"(擬似データ)


class PropertyRegisterRequest(BaseModel):
    property_data: dict


class PropertyRegisterResponse(BaseModel):
    success: bool
    normalized: dict


# ---------- Recommend (Phase2: README 5.3節「レコメンド系」) ----------
class RecommendRequest(BaseModel):
    table_name: str  # customers | orders | products
    id: int
    max_results: int = 5
    include_explanation: bool = False  # ルールベースの一致理由文を付与するか(AIではない)


class RecommendResult(BaseModel):
    id: int
    text: str
    score: float
    explanation: str | None = None


class RecommendResponse(BaseModel):
    table_name: str
    source_id: int
    results: list[RecommendResult]


# ---------- Local AI Assist (Phase3: README 5.4.2「ビジネスアシスタント」) ----------
class AssistRequest(BaseModel):
    message: str
    screen_context: dict | None = None
    conversation_id: str | None = None


class AssistResponse(BaseModel):
    response: str
    conversation_id: str
    suggested_actions: list[str]
    provider: str


# ---------- Conversational Input (Phase3: README 5.4.7「自然言語→フォームデータ変換」) ----------
class ConversationalInputRequest(BaseModel):
    message: str
    target_screen: str
    screen_context: dict | None = None
    conversation_id: str | None = None


class InputMapping(BaseModel):
    field: str
    value: str
    confidence: str  # high(AIが直接抽出) | medium(エンティティ解決で補完)


class ConversationalInputResponse(BaseModel):
    response: str
    conversation_id: str
    input_mappings: list[InputMapping]
    intent: str
    missing_fields: list[str]
    confidence: float


# 2026-09-01: OCR(OcrRegisterRequest/Response)と同じ「登録用データを作る」導線用。
class ConversationalInputRegisterRequest(BaseModel):
    fields: dict  # input_mappingsを{field: value}に組み直したものをそのまま渡す想定
    target_screen: str  # "order-input" | "customer-register" | "estimate-mgmt" | "invoice-mgmt" | "supplier-mgmt"


class ConversationalInputRegisterResponse(BaseModel):
    success: bool
    normalized: dict  # レガシーフォームのフィールド名(Name/Tel/customerId/...)に正規化済み
    entry_entity: str
