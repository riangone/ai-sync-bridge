from fastapi import APIRouter, Depends, HTTPException

from app.deps import get_admin_service, get_ai_provider, get_demo_store, get_notification_center, get_workflow_engine
from app.models.schemas import InsightResponse, WorkflowEvent, WorkflowRule, WorkflowRuleCreate, WorkflowRunResult
from app.services import insight_service
from app.services.admin_service import AdminService
from app.services.ai_client import AiProvider
from app.services.demo_data import DemoDataStore
from app.services.notification_service import NotificationCenter
from app.services.workflow_service import WorkflowEngine

router = APIRouter(prefix="/api/workflows", tags=["workflows"])

# action -> 通知レベルの対応(承認系は警告扱いで管理画面/通知パネルで目立たせる)
_LEVEL_BY_ACTION = {"flag_approval": "warning", "notify": "info", "flag_followup": "info"}


@router.get("/rules", response_model=list[WorkflowRule])
def list_rules(engine: WorkflowEngine = Depends(get_workflow_engine)):
    return engine.list_rules()


@router.post("/rules", response_model=WorkflowRule, status_code=201)
def create_rule(
    payload: WorkflowRuleCreate,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    admin: AdminService = Depends(get_admin_service),
):
    rule = engine.add_rule(payload.model_dump())
    admin.audit_log.record("admin", "create_workflow_rule", f"ルール追加: {rule['name']}")
    return rule


@router.delete("/rules/{rule_id}", status_code=204)
def delete_rule(
    rule_id: int,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    admin: AdminService = Depends(get_admin_service),
):
    if not engine.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="Rule not found")
    admin.audit_log.record("admin", "delete_workflow_rule", f"ルール削除: id={rule_id}")


@router.post("/run", response_model=WorkflowRunResult)
def run_workflows(
    engine: WorkflowEngine = Depends(get_workflow_engine),
    store: DemoDataStore = Depends(get_demo_store),
    notifications: NotificationCenter = Depends(get_notification_center),
):
    new_events = engine.evaluate(store)
    # 発火イベントは通知センターにも流し込み、Chrome拡張の通知パネル/未読バッジに反映する
    # (ワークフローと通知を別モジュールに分けたのは、通知センターが将来
    #  他の発生源(OCR失敗・予測分析アラート等)からも使い回せるようにするため)。
    for event in new_events:
        notifications.push(
            source="workflow",
            level=_LEVEL_BY_ACTION.get(event["action"], "info"),
            title=event["rule_name"],
            message=event["message"],
            ref_type=event["entity"],
            ref_id=event["entity_id"],
        )
    return {
        "evaluated_customers": len(store.list_customers()),
        "evaluated_orders": len(store.list_orders()),
        "new_events": new_events,
    }


@router.get("/history", response_model=list[WorkflowEvent])
def get_history(limit: int = 50, engine: WorkflowEngine = Depends(get_workflow_engine)):
    return engine.get_history(limit)


# ルール評価自体はAI非依存(条件式ベース)のまま。発火傾向の解釈だけをオプトインでAIに委譲する。
@router.get("/history/insight", response_model=InsightResponse)
async def history_insight(
    limit: int = 50,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    ai: AiProvider = Depends(get_ai_provider),
):
    history = engine.get_history(limit)
    comment = await insight_service.interpret_workflow_history(ai, history)
    return InsightResponse(comment=comment, provider=ai.name)
