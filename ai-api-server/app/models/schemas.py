"""Pydantic スキーマ定義（言語非依存仕様の Models 層）"""
from datetime import datetime
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
    type: str  # ranked-bar | ranked-bar-grouped
    unit: str
    categories: list[str]
    series: list[ChartSeries]


class CrossAnalysisResponse(BaseModel):
    report: str
    label: str
    generated_at: datetime
    summary: dict
    chart: ChartData
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
    generated_at: datetime
    summary: dict
    chart: ChartData
    rows: list[dict]
    warnings: list[str] = []
    provider: str


# ---------- Workflow Engine ----------
class WorkflowRule(BaseModel):
    id: int
    name: str
    entity: str  # customer | order
    field: str
    operator: str  # >, <, >=, <=, ==, !=, contains
    value: str
    action: str  # flag_approval | notify | flag_followup
    message_template: str
    enabled: bool = True


class WorkflowRuleCreate(BaseModel):
    name: str
    entity: str
    field: str
    operator: str
    value: str
    action: str
    message_template: str
    enabled: bool = True


class WorkflowEvent(BaseModel):
    id: int
    rule_id: int
    rule_name: str
    entity: str
    entity_id: int
    action: str
    message: str
    triggered_at: datetime


class WorkflowRunResult(BaseModel):
    evaluated_customers: int
    evaluated_orders: int
    new_events: list[WorkflowEvent]


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


# ---------- Admin ----------
class AdminStats(BaseModel):
    demo_mode: bool
    ai_provider: str
    vector_backend: str
    customer_count: int
    order_count: int
    workflow_rule_count: int
    workflow_event_count: int
    unread_notification_count: int
    generated_at: datetime


class AuditLogEntry(BaseModel):
    id: int
    actor: str
    action: str
    detail: str
    at: datetime
