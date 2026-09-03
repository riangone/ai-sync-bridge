from fastapi import APIRouter, Depends, HTTPException

from app.deps import (
    get_admin_service,
    get_ai_provider,
    get_workflow_engine,
    get_workflow_step_runner,
)
from app.models.schemas import (
    InsightResponse,
    WorkflowDefinition,
    WorkflowDefinitionCreate,
    WorkflowDefinitionUpdate,
    WorkflowExecuteRequest,
    WorkflowExecutionResult,
    WorkflowToggleResult,
    WorkflowTriggerEvalRequest,
    WorkflowTriggerEvalResult,
)
from app.services import insight_service
from app.services.admin_service import AdminService
from app.services.ai_client import AiProvider
from app.services.workflow_service import WorkflowEngine
from app.services.workflow_step_runner import WorkflowStepRunner

# README 5.2/6.2 の "/api/workflow" 単数形ではなく、コードベース全体の既存規約
# (/api/customers, /api/inventory, /api/purchase-order, ...) に合わせて
# "/api/workflows" 複数形プレフィックスを維持する(#8のポート番号方針と同じ判断:
# パス単数/複数の表記差は機能そのものではないため、既存コードベースの規約を優先する)。
router = APIRouter(prefix="/api/workflows", tags=["workflows"])


@router.get("", response_model=list[WorkflowDefinition])
def list_workflows(engine: WorkflowEngine = Depends(get_workflow_engine)):
    return engine.list_workflows()


@router.post("", response_model=WorkflowDefinition, status_code=201)
def create_workflow(
    payload: WorkflowDefinitionCreate,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    admin: AdminService = Depends(get_admin_service),
):
    wf = engine.add_workflow(payload.model_dump())
    admin.audit_log.record("admin", "create_workflow", f"ワークフロー作成: {wf['name']}")
    return wf


@router.get("/{workflow_id}", response_model=WorkflowDefinition)
def get_workflow(workflow_id: str, engine: WorkflowEngine = Depends(get_workflow_engine)):
    wf = engine.get_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    return wf


@router.put("/{workflow_id}", response_model=WorkflowDefinition)
def update_workflow(
    workflow_id: str,
    payload: WorkflowDefinitionUpdate,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    admin: AdminService = Depends(get_admin_service),
):
    wf = engine.update_workflow(workflow_id, payload.model_dump(exclude_unset=True))
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    admin.audit_log.record("admin", "update_workflow", f"ワークフロー更新: {wf['name']}")
    return wf


@router.delete("/{workflow_id}", status_code=204)
def delete_workflow(
    workflow_id: str,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    admin: AdminService = Depends(get_admin_service),
):
    if not engine.delete_workflow(workflow_id):
        raise HTTPException(status_code=404, detail="Workflow not found")
    admin.audit_log.record("admin", "delete_workflow", f"ワークフロー削除: id={workflow_id}")


@router.patch("/{workflow_id}/toggle", response_model=WorkflowToggleResult)
def toggle_workflow(
    workflow_id: str,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    admin: AdminService = Depends(get_admin_service),
):
    wf = engine.toggle_workflow(workflow_id)
    if wf is None:
        raise HTTPException(status_code=404, detail="Workflow not found")
    admin.audit_log.record("admin", "toggle_workflow", f"ワークフロー有効/無効切替: {wf['name']} -> {wf['enabled']}")
    return {"id": wf["id"], "enabled": wf["enabled"]}


@router.post("/{workflow_id}/execute", response_model=WorkflowExecutionResult)
async def execute_workflow(
    workflow_id: str,
    payload: WorkflowExecuteRequest = WorkflowExecuteRequest(),
    engine: WorkflowEngine = Depends(get_workflow_engine),
    runner: WorkflowStepRunner = Depends(get_workflow_step_runner),
):
    try:
        return await engine.execute(workflow_id, payload.context, runner)
    except KeyError:
        raise HTTPException(status_code=404, detail="Workflow not found")


@router.post("/evaluate-triggers", response_model=WorkflowTriggerEvalResult)
def evaluate_triggers(
    payload: WorkflowTriggerEvalRequest,
    engine: WorkflowEngine = Depends(get_workflow_engine),
):
    matched = engine.evaluate_triggers(payload.current_screen_type, payload.changed_table)
    return {"matched_workflows": matched}


@router.get("/history/list", response_model=list[WorkflowExecutionResult])
def get_history(limit: int = 50, engine: WorkflowEngine = Depends(get_workflow_engine)):
    return engine.get_execution_history(limit)


# ワークフロー実行そのものはAI非依存(ステップ設定に基づく決定的な実行)のまま。
# 実行傾向の解釈だけをオプトインでAIに委譲する(既存の与信/在庫レポートと同一パターン)。
@router.get("/history/insight", response_model=InsightResponse)
async def history_insight(
    limit: int = 50,
    engine: WorkflowEngine = Depends(get_workflow_engine),
    ai: AiProvider = Depends(get_ai_provider),
):
    history = engine.get_execution_history(limit)
    comment = await insight_service.interpret_workflow_history(ai, history)
    return InsightResponse(comment=comment, provider=ai.name)
