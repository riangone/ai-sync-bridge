"""
/api/bridge — Legacy-to-AI 増分ブリッジのコアAPI(業種非依存)。

  GET  /api/bridge/whoami        呼び出し主体(Principal)の確認
  POST /api/bridge/search        権限フィルタ付き検索(全件監査)
  POST /api/bridge/ask           権限付きRAG: 閲覧可能な文書だけを根拠にAIが回答(全件監査)
  DELETE /api/bridge/ask/{sid}   会話履歴のリセット(呼び出し主体の分のみ)
  GET  /api/bridge/status        同期状態・カーソル・件数            [bridge_admin]
  POST /api/bridge/sync          差分同期の実行                      [bridge_admin]
  GET  /api/bridge/audit         監査ログ参照                        [bridge_admin]
  GET  /api/bridge/audit/verify  ハッシュチェーン検証                [bridge_admin]
"""
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field

from app.bridge.acl import Principal, require_admin
from app.bridge.runtime import BridgeRuntime
from app.deps import get_bridge
from app.services.ai_client import AIProviderError

router = APIRouter(prefix="/api/bridge", tags=["bridge"])


def principal_dep(request: Request, bridge: BridgeRuntime = Depends(get_bridge)) -> Principal:
    return bridge.resolver.resolve(request)


def admin_dep(p: Principal = Depends(principal_dep)) -> Principal:
    require_admin(p)
    return p


class BridgeSearchRequest(BaseModel):
    query: str = Field(min_length=1, max_length=2000)
    top_k: int = Field(default=5, ge=1, le=50)
    entities: list[str] | None = None


class BridgeAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    session_id: str = Field(default="default", max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=20)
    entities: list[str] | None = None


class BridgeSyncRequest(BaseModel):
    source: str | None = None
    entity: str | None = None


@router.get("/whoami")
def whoami(p: Principal = Depends(principal_dep), bridge: BridgeRuntime = Depends(get_bridge)):
    return {"principal": p.to_json(), "auth_mode": bridge.resolver.mode, "is_admin": p.is_admin}


@router.post("/search")
async def search(body: BridgeSearchRequest, p: Principal = Depends(principal_dep),
                 bridge: BridgeRuntime = Depends(get_bridge)):
    return await bridge.search(p, body.query, body.top_k, body.entities)


@router.post("/ask")
async def ask(body: BridgeAskRequest, p: Principal = Depends(principal_dep),
              bridge: BridgeRuntime = Depends(get_bridge)):
    return await answer_or_http_error(bridge, p, body.question, body.session_id, body.top_k, body.entities)


@router.delete("/ask/{session_id}")
def reset_ask(session_id: str, p: Principal = Depends(principal_dep), bridge: BridgeRuntime = Depends(get_bridge)):
    bridge.reset_conversation(p, session_id)
    return {"ok": True}


async def answer_or_http_error(bridge: BridgeRuntime, p: Principal, question: str, session_id: str,
                               top_k: int | None = None, entities: list[str] | None = None) -> dict:
    if not bridge.answerer.enabled:
        raise HTTPException(status_code=503, detail="LLM が未設定のため回答生成は利用できません")
    try:
        return await bridge.ask(p, question, session_id, top_k, entities)
    except AIProviderError as e:
        raise HTTPException(status_code=502, detail=str(e)) from None


@router.get("/status")
def status(_: Principal = Depends(admin_dep), bridge: BridgeRuntime = Depends(get_bridge)):
    return bridge.status()


@router.post("/sync")
async def sync(body: BridgeSyncRequest | None = None, p: Principal = Depends(admin_dep),
               bridge: BridgeRuntime = Depends(get_bridge)):
    body = body or BridgeSyncRequest()
    try:
        return await bridge.sync(actor=p.user_id, source=body.source, entity=body.entity)
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from None


@router.get("/audit")
def audit(kind: str | None = Query(default=None, description="例: retrieval / sync.* "),
          limit: int = 100, since_seq: int = 0,
          _: Principal = Depends(admin_dep), bridge: BridgeRuntime = Depends(get_bridge)):
    return {"items": bridge.audit.query(kind=kind, limit=limit, since_seq=since_seq)}


@router.get("/audit/verify")
def audit_verify(_: Principal = Depends(admin_dep), bridge: BridgeRuntime = Depends(get_bridge)):
    return bridge.audit.verify()
