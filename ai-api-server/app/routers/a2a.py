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
    if not bridge.a2a.discoverable:
        raise HTTPException(status_code=404, detail="Agent Card publication is currently disabled (non-discoverable)")
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


class InboundInvitationRequest(BaseModel):
    invite_code: str = Field(min_length=1, max_length=64)
    from_agent: str = Field(min_length=1, max_length=120)
    from_peer_name: str = Field(min_length=1, max_length=50)
    note: str = Field(default="", max_length=300)


class InboundDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    from_agent: str = Field(default="", max_length=120)


@router.post("/a2a/invitations")
def a2a_receive_invitation(
    body: InboundInvitationRequest,
    _: Principal = Depends(_principal_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    if not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="A2A adapter is disabled")
    inv = bridge.a2a.receive_invitation(
        invite_code=body.invite_code,
        from_agent=body.from_agent,
        from_peer_name=body.from_peer_name,
        note=body.note,
    )
    return {"received": True, "invitation": inv.to_dict()}


@router.post("/a2a/invitations/{invite_code}/decision")
def a2a_receive_invitation_decision(
    invite_code: str,
    body: InboundDecisionRequest,
    _: Principal = Depends(_principal_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    if not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="A2A adapter is disabled")
    matched = bridge.a2a.receive_invitation_decision(
        invite_code=invite_code,
        decision=body.decision,
        from_agent=body.from_agent,
    )
    return {
        "acknowledged": True,
        "matched_peer": matched.name if matched else None,
        "status": matched.status if matched else None,
    }


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
        "discoverable": bridge.a2a.discoverable,
        "agent": bridge.a2a.agent_name,
        "peers": bridge.a2a.peer_summary(principal),
        "incoming_invitations": bridge.a2a.list_incoming_invitations(),
    }


class DemoPublishRequest(BaseModel):
    discoverable: bool


class DemoDiscoverRequest(BaseModel):
    target: str = Field(min_length=1, max_length=50)


class DemoPeerActionRequest(BaseModel):
    action: str = Field(pattern="^(invite|approve|reject|block|unblock)$")


class DemoVerifyAuthRequest(BaseModel):
    peer: str = Field(min_length=1, max_length=50)
    mode: str = Field(default="valid", pattern="^(valid|anonymous|invalid)$")


@router.get("/api/a2a/demo/governance")
def demo_governance_state(
    request: Request,
    persona: str | None = None,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    principal = _persona(bridge.demo, persona).principal if (persona and bridge.demo) else None
    base_url = str(request.base_url).rstrip("/")
    card = bridge.a2a.agent_card(base_url=base_url)
    return {
        "agent": bridge.a2a.agent_name,
        "description": bridge.a2a.agent_description,
        "discoverable": bridge.a2a.discoverable,
        "well_known_path": "/.well-known/agent.json",
        "agent_card": card,
        "yaml_snippet": (
            "a2a:\n"
            f"  enabled: true\n"
            f"  discoverable: {'true' if bridge.a2a.discoverable else 'false'}\n"
            f"  name: \"{bridge.a2a.agent_name}\"\n"
            "  peers:\n"
            + "\n".join(
                f"    - name: {p.name}\n"
                f"      status: {p.status}\n"
                f"      allowed_roles: [{', '.join(sorted(p.allowed_roles))}]\n"
                f"      api_key: \"${{A2A_KEY_{p.name.upper()}}}\""
                for p in bridge.a2a.peers.values()
            )
        ),
        "peers": bridge.a2a.peer_summary(principal),
        "incoming_invitations": bridge.a2a.list_incoming_invitations(),
    }


@router.post("/api/a2a/demo/publish")
def demo_toggle_publish(
    body: DemoPublishRequest,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    bridge.a2a.discoverable = body.discoverable
    bridge.audit.append(
        "a2a.governance.publish_changed",
        "demo-governance",
        detail={"discoverable": body.discoverable},
    )
    return {
        "discoverable": bridge.a2a.discoverable,
        "http_status_if_probed": 200 if bridge.a2a.discoverable else 404,
        "message": (
            "公開ON: GET /.well-known/agent.json が AgentCard (HTTP 200) を返します"
            if bridge.a2a.discoverable
            else "非公開OFF: GET /.well-known/agent.json は HTTP 404 を返し、外部からの自動発見を遮断します"
        ),
    }


@router.post("/api/a2a/demo/discover")
async def demo_discover(
    body: DemoDiscoverRequest,
    request: Request,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    target = body.target.strip().lower()
    if target == "self":
        if not bridge.a2a.discoverable:
            return {
                "target": "self",
                "found": False,
                "http_status": 404,
                "message": "HTTP 404: 現在このAgentは非公開（discoverable=false）のため AgentCard を取得できません",
            }
        card = bridge.a2a.agent_card(base_url=str(request.base_url).rstrip("/"))
        return {
            "target": "self",
            "found": True,
            "http_status": 200,
            "card": card,
            "message": f"HTTP 200: 自Agent ({card['name']}) の AgentCard を公開エンドポイントから取得しました",
        }
    if target == "unknown-ext":
        return {
            "target": "unknown-ext",
            "found": False,
            "http_status": 403,
            "message": "ホワイトリスト外のため探索拒否: bridge.yaml に未登録の任意URLへの自動探索は SSRF・不正連携防止のため遮断されます",
        }
    peer = bridge.a2a.peers.get(target)
    if not peer:
        raise HTTPException(status_code=404, detail=f"unknown target: {target}")
    try:
        card = await bridge.a2a.discover_peer(target)
        return {
            "target": target,
            "found": True,
            "http_status": 200,
            "card": card,
            "message": f"HTTP 200: {card.get('name', target)} の /.well-known/agent.json からリアルタイムに能力(Skills)と認証方式を発見しました",
        }
    except Exception as exc:
        log_upstream("demo a2a discover failed", exc)
        return {
            "target": target,
            "found": False,
            "http_status": 502,
            "message": f"Peer ({target}) の AgentCard 取得に失敗しました: {type(exc).__name__}",
        }


class DemoInvitationRespondRequest(BaseModel):
    decision: str = Field(pattern="^(approve|reject)$")


@router.post("/api/a2a/demo/peers/{peer_name}/action")
async def demo_peer_action(
    peer_name: str,
    body: DemoPeerActionRequest,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    if body.action == "invite":
        try:
            res = await bridge.a2a.send_peer_invitation(peer_name)
        except KeyError:
            raise HTTPException(status_code=404, detail=f"unknown peer: {peer_name}") from None
        return {
            **res,
            "peers": bridge.a2a.peer_summary(),
            "incoming_invitations": bridge.a2a.list_incoming_invitations(),
        }
    action_to_status = {
        "approve": "active",
        "reject": "rejected",
        "block": "blocked",
        "unblock": "active",
    }
    try:
        peer = bridge.a2a.set_peer_status(peer_name, action_to_status[body.action])
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown peer: {peer_name}") from None
    return {
        "peer": peer.name,
        "status": peer.status,
        "invite_code": peer.invite_code,
        "peers": bridge.a2a.peer_summary(),
        "incoming_invitations": bridge.a2a.list_incoming_invitations(),
    }


@router.post("/api/a2a/demo/invitations/{invite_code}/respond")
async def demo_respond_invitation(
    invite_code: str,
    body: DemoInvitationRespondRequest,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    try:
        res = await bridge.a2a.respond_to_invitation(invite_code, body.decision)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown invitation: {invite_code}") from None
    return {
        **res,
        "peers": bridge.a2a.peer_summary(),
        "incoming_invitations": bridge.a2a.list_incoming_invitations(),
    }


@router.post("/api/a2a/demo/verify-auth")
async def demo_verify_auth(
    body: DemoVerifyAuthRequest,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    try:
        return await bridge.a2a.verify_peer_auth(body.peer, mode=body.mode)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown peer: {body.peer}") from None
    except Exception as exc:
        log_upstream("demo a2a verify-auth failed", exc)
        raise HTTPException(status_code=502, detail="Peer への認証疎通テストに失敗しました") from None


@router.post("/api/a2a/demo/reset")
def demo_reset_governance(
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    bridge.a2a.reset_governance_demo()
    return {
        "discoverable": bridge.a2a.discoverable,
        "peers": bridge.a2a.peer_summary(),
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
