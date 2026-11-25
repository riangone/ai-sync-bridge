"""
A2A (Agent-to-Agent) Protocol Router.

  GET  /.well-known/agent.json        Agent Card discovery (public capability metadata)
  POST /a2a                           JSON-RPC 2.0 endpoint (tasks/send, tasks/get, tasks/cancel)  [key]
  GET  /api/a2a/peers                 List configured peer agents                                  [key]
  POST /api/a2a/federated-ask         Local Bridge + parallel A2A peer delegation                  [key]
  GET  /api/a2a/demo/peers            公開デモ: 指定ペルソナが委譲できる Peer の一覧
  POST /api/a2a/demo/federated-ask    公開デモ: 指定ペルソナの権限でローカル回答 + Peer 委譲

[key] の経路は匿名主体を拒否する。federated-ask は本 Agent の Peer 用キーで相手を呼ぶため、
匿名を通すと「キーなしの利用者が Agent の権限で相手システムを読む」昇格経路になる。
公開ページからは demo 経路だけを使い、ペルソナ・回数制限・応答の許可リストは
/api/bridge/demo と同じ DemoGateway の不変条件に従う(app/bridge/demo.py)。
"""
from __future__ import annotations

import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field

from app.bridge import demo as demo_api
from app.bridge.acl import ANONYMOUS, Principal
from app.bridge.demo import DemoGateway, Persona, client_ip
from app.bridge.runtime import BridgeRuntime
from app.deps import get_bridge
from app.public_errors import AI_RATE_LIMITED, AI_UNAVAILABLE, log_upstream
from app.services.ai_client import AIProviderError, AIRateLimitError

router = APIRouter(tags=["a2a"])


def _principal_dep(request: Request, bridge: BridgeRuntime = Depends(get_bridge)) -> Principal:
    principal = bridge.resolver.resolve(request)
    if principal is ANONYMOUS:
        raise HTTPException(status_code=401, detail="API key required")
    return principal


class FederatedAskRequest(BaseModel):
    question: str = Field(min_length=1, max_length=2000)
    peers: list[str] | None = None
    session_id: str = Field(default="federated", max_length=100)
    top_k: int | None = Field(default=None, ge=1, le=20)


@router.get("/.well-known/agent.json")
def agent_card(request: Request, bridge: BridgeRuntime = Depends(get_bridge)):
    if not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="A2A adapter is disabled")
    base_url = str(request.base_url).rstrip("/")
    return bridge.a2a.agent_card(base_url=base_url)


@router.post("/a2a")
async def a2a_rpc(
    payload: dict[str, Any],
    principal: Principal = Depends(_principal_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    if not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="A2A adapter is disabled")
    return await bridge.a2a.handle_rpc(principal, payload)


@router.get("/api/a2a/peers")
def list_peers(
    _: Principal = Depends(_principal_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    return {
        "agent": bridge.a2a.agent_name,
        "peers": [
            {"name": p.name, "url": p.url, "description": p.description}
            for p in bridge.a2a.peers.values()
        ],
    }


@router.post("/api/a2a/federated-ask")
async def federated_ask(
    body: FederatedAskRequest,
    principal: Principal = Depends(_principal_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    if not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="A2A adapter is disabled")
    return await bridge.a2a.federated_ask(
        principal,
        body.question,
        peers=body.peers,
        session_id=body.session_id,
        top_k=body.top_k,
    )


class DemoFederatedAskRequest(BaseModel):
    persona: str = Field(max_length=50)
    question: str = Field(min_length=1, max_length=500)


def _demo_dep(bridge: BridgeRuntime = Depends(get_bridge)) -> DemoGateway:
    if bridge.demo is None or not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="このデモでは利用できません")
    return bridge.demo


def _persona(demo: DemoGateway, persona_id: str) -> Persona:
    persona = demo.personas.get(persona_id)
    if persona is None:
        raise HTTPException(status_code=404, detail="unknown persona")
    return persona


def _public_local(res: dict) -> dict:
    return demo_api.public_answer(res) if "answer" in res else demo_api.public_search(res)


def _public_peer(name: str, res: dict) -> dict:
    meta = res.get("metadata") or {}
    return {
        "peer": name,
        "status": res.get("status", "unknown"),
        "answer": res.get("answer") or "",
        "acl_filtered": meta.get("acl_filtered"),
        "audit_id": meta.get("audit_id"),
        "error": res.get("error") if res.get("status") not in ("completed", "input-required") else None,
    }


@router.get("/api/a2a/demo/peers")
def demo_list_peers(persona: str | None = None, bridge: BridgeRuntime = Depends(get_bridge)):
    if bridge.demo is None or not bridge.a2a.enabled:
        return {"enabled": False, "agent": "", "peers": []}
    principal = _persona(bridge.demo, persona).principal if persona else None
    return {
        "enabled": True,
        "agent": bridge.a2a.agent_name,
        "peers": [
            {"name": p.name, "description": p.description,
             "allowed": principal is None or p.allows(principal)}
            for p in bridge.a2a.peers.values()
        ],
    }


@router.post("/api/a2a/demo/federated-ask")
async def demo_federated_ask(body: DemoFederatedAskRequest, request: Request,
                             demo: DemoGateway = Depends(_demo_dep),
                             bridge: BridgeRuntime = Depends(get_bridge)):
    persona = _persona(demo, body.persona)
    principal = persona.principal
    # LLM はローカル1回 + 委譲できる Peer ごとに1回。比較ボタンと同じ予算から消費する
    calls = 1 + sum(1 for p in bridge.a2a.peers.values() if p.allows(principal))
    ip = client_ip(request)
    if not all(demo.ask_limiter.allow(ip) for _ in range(calls)):
        raise HTTPException(status_code=429, detail="AI回答の利用回数の上限に達しました。しばらくしてからお試しください")
    # ペルソナは全訪問者で共有するため、推測できないセッションを毎回発行して終了後に破棄する
    session_id = f"demo-a2a-{uuid.uuid4().hex}"
    try:
        res = await bridge.a2a.federated_ask(principal, body.question, session_id=session_id)
    except AIRateLimitError:
        raise HTTPException(status_code=429, detail=AI_RATE_LIMITED) from None
    except AIProviderError as e:
        log_upstream("demo a2a answer failed", e)
        raise HTTPException(status_code=502, detail=AI_UNAVAILABLE) from None
    finally:
        bridge.reset_conversation(principal, session_id)
    return {
        "agent": res["agent"],
        "persona": {"id": persona.id, "label": persona.label},
        "local": _public_local(res["local"]),
        "peers": [_public_peer(name, r) for name, r in res["peers"].items()],
    }
