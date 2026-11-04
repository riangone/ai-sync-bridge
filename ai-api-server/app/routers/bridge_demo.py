"""
/api/bridge/demo — 公開デモページ専用の入口。キーなしで呼べるので、返す内容と回数を絞る。
設計と不変条件は app/bridge/demo.py を参照。

  GET  /api/bridge/demo/personas      切り替え可能な主体の一覧(表示名のみ)
  POST /api/bridge/demo/search        指定ペルソナの権限で検索
  POST /api/bridge/demo/ask           指定ペルソナの権限でAI回答(履歴なし)
  POST /api/bridge/demo/sync          差分同期(クールダウン中は前回の結果)
  GET  /api/bridge/demo/audit         監査ログの要約(検索語・回答本文なし)
  GET  /api/bridge/demo/audit/verify  ハッシュチェーン検証
"""
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.bridge import demo as demo_api
from app.bridge.demo import DemoGateway, Persona, client_ip
from app.bridge.runtime import BridgeRuntime
from app.deps import get_bridge
from app.services.ai_client import AIProviderError

router = APIRouter(prefix="/api/bridge/demo", tags=["bridge-demo"])

DEMO_SYNC_ACTOR = "demo:public"
SEARCH_TOP_K = 5
AUDIT_ITEMS = 15


class DemoSearchRequest(BaseModel):
    persona: str = Field(max_length=50)
    query: str = Field(min_length=1, max_length=500)


class DemoAskRequest(BaseModel):
    persona: str = Field(max_length=50)
    question: str = Field(min_length=1, max_length=500)


def demo_dep(bridge: BridgeRuntime = Depends(get_bridge)) -> DemoGateway:
    if bridge.demo is None:
        raise HTTPException(status_code=404, detail="このデモでは利用できません")
    return bridge.demo


def read_limit(request: Request, demo: DemoGateway = Depends(demo_dep)) -> DemoGateway:
    if not demo.read_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="アクセスが集中しています。しばらくしてからお試しください")
    return demo


def _persona(demo: DemoGateway, persona_id: str) -> Persona:
    persona = demo.personas.get(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="unknown persona")
    return persona


@router.get("/personas")
def personas(demo: DemoGateway = Depends(demo_dep)):
    return {"personas": [{"id": p.id, "label": p.label, "note": p.note} for p in demo.personas.values()]}


@router.post("/search")
async def search(body: DemoSearchRequest, demo: DemoGateway = Depends(read_limit),
                 bridge: BridgeRuntime = Depends(get_bridge)):
    persona = _persona(demo, body.persona)
    return demo_api.public_search(await bridge.search(persona.principal, body.query, SEARCH_TOP_K))


@router.post("/ask")
async def ask(body: DemoAskRequest, request: Request, demo: DemoGateway = Depends(demo_dep),
              bridge: BridgeRuntime = Depends(get_bridge)):
    persona = _persona(demo, body.persona)
    if not bridge.answerer.enabled:
        raise HTTPException(status_code=503, detail="AI回答は現在利用できません")
    if not demo.ask_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="AI回答の利用回数の上限に達しました。しばらくしてからお試しください")
    session_id = f"demo-{uuid.uuid4().hex}"
    try:
        return demo_api.public_answer(await bridge.ask(persona.principal, body.question, session_id))
    except AIProviderError:
        # 上流のエラー文面は公開しない(詳細はサーバー側のログで確認する)
        raise HTTPException(status_code=502, detail="AIサービスが一時的に利用できません") from None
    finally:
        bridge.reset_conversation(persona.principal, session_id)


@router.post("/sync")
async def sync(demo: DemoGateway = Depends(read_limit), bridge: BridgeRuntime = Depends(get_bridge)):
    cached = demo.claim_sync()
    if cached is not None:
        return cached
    result = demo_api.public_sync(await bridge.sync(actor=DEMO_SYNC_ACTOR))
    demo.store_sync(result)
    return result


@router.get("/audit")
def audit(_: DemoGateway = Depends(read_limit), bridge: BridgeRuntime = Depends(get_bridge)):
    return {"items": [demo_api.public_audit_item(it) for it in bridge.audit.query(limit=AUDIT_ITEMS)]}


@router.get("/audit/verify")
def audit_verify(_: DemoGateway = Depends(read_limit), bridge: BridgeRuntime = Depends(get_bridge)):
    return demo_api.public_verify(bridge.audit.verify())
