"""
A2A (Agent-to-Agent) Protocol Router.

  GET  /.well-known/agent.json        Agent Card discovery (public capability metadata)
  POST /a2a                           JSON-RPC 2.0 endpoint (tasks/send, tasks/get, tasks/cancel)  [key]
  GET  /api/a2a/peers                 List configured peer agents                                  [key]
  POST /api/a2a/federated-ask         Local Bridge + parallel A2A peer delegation                  [key]
  GET  /api/a2a/demo/peers            公開デモ: 指定ペルソナが委譲できる Peer の一覧
  POST /api/a2a/demo/federated-ask    公開デモ: 指定ペルソナの権限でローカル回答 + Peer 委譲(+統合回答)
  GET  /api/a2a/demo/topology         公開デモ: 自分から見た信頼関係(直接 Peer と中継ルール)
  GET  /api/a2a/demo/inbound-log      公開デモ: 受信した A2A 依頼の経路・縮退の記録(本文なし)
  POST /api/a2a/demo/acl-probe        公開デモ: 設定済みの機密狙いの質問を Peer に投げ、漏洩がないか判定

受信の入口(/a2a, /a2a/invitations*)は、キーから引いた主体を自分の設定(peers[].inbound_user_id)で
Peer に対応づける。遮断・未承認の Peer は 403、Peer ごとの回数上限を超えたら 429。
公開デモのガバナンス操作は全訪問者で共有されるため、IP ごとに回数を絞り、TTL で初期状態へ戻す。

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
from app.bridge.a2a import A2AGateError
from app.bridge.acl import ANONYMOUS, Principal
from app.bridge.demo import DemoGateway, Persona, client_ip
from app.bridge.runtime import BridgeRuntime
from app.deps import get_bridge
from app.public_errors import AI_RATE_LIMITED, AI_UNAVAILABLE, log_upstream
from app.services.ai_client import AIProviderError, AIRateLimitError
from app.services.rate_limit import SlidingWindowLimiter

router = APIRouter(tags=["a2a"])

# 公開デモのガバナンス変更(遮断・招待など)の回数。読み取りは DemoGateway.read_limiter を使う
_gov_limiter = SlidingWindowLimiter(30, 600)


def _gate(bridge: BridgeRuntime, principal: Principal, purpose: str):
    try:
        return bridge.a2a.check_inbound(principal, purpose=purpose)
    except A2AGateError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None


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
    peer = _gate(bridge, principal, "task")
    return await bridge.a2a.handle_rpc(principal, payload, peer)


class InboundInvitationRequest(BaseModel):
    invite_code: str = Field(pattern=r"^inv_[A-Za-z0-9]{8,32}$")
    from_agent: str = Field(default="", max_length=120)  # 表示用。差出人はキーから決める
    note: str = Field(default="", max_length=300)


class InboundDecisionRequest(BaseModel):
    decision: str = Field(pattern="^(approved|rejected)$")
    from_agent: str = Field(default="", max_length=120)


@router.post("/a2a/invitations")
def a2a_receive_invitation(
    body: InboundInvitationRequest,
    principal: Principal = Depends(_principal_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    if not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="A2A adapter is disabled")
    peer = _gate(bridge, principal, "handshake")
    try:
        inv = bridge.a2a.receive_invitation(
            peer,
            invite_code=body.invite_code,
            from_agent=body.from_agent,
            note=body.note,
        )
    except A2AGateError as e:
        raise HTTPException(status_code=e.status, detail=e.message) from None
    return {"received": True, "invitation": inv.to_dict()}


@router.post("/a2a/invitations/{invite_code}/decision")
def a2a_receive_invitation_decision(
    invite_code: str,
    body: InboundDecisionRequest,
    principal: Principal = Depends(_principal_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    if not bridge.a2a.enabled:
        raise HTTPException(status_code=404, detail="A2A adapter is disabled")
    peer = _gate(bridge, principal, "handshake")
    matched = bridge.a2a.receive_invitation_decision(
        peer,
        invite_code=invite_code,
        decision=body.decision,
        from_agent=body.from_agent,
    )
    if matched is None:
        # 自分がこの相手に送った有効な招待ではない(別の Peer 宛て・期限切れ・使用済み)
        raise HTTPException(status_code=404, detail="no pending invitation for this peer")
    return {
        "acknowledged": True,
        "matched_peer": matched.name if matched else None,
        "status": matched.status if matched else None,
    }


def _not_peer_dep(principal: Principal = Depends(_principal_dep),
                  bridge: BridgeRuntime = Depends(get_bridge)) -> Principal:
    """運用者・利用者のキーだけを通す。Peer のキーは /a2a 以外の A2A 経路を使えない
    (接続先一覧の覗き見と、federated-ask を使った借道を防ぐ)。"""
    if bridge.a2a.peer_for_principal(principal) is not None:
        raise HTTPException(status_code=403, detail="peer agent keys are limited to /a2a")
    return principal


@router.get("/api/a2a/peers")
def list_peers(
    _: Principal = Depends(_not_peer_dep),
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
    principal: Principal = Depends(_not_peer_dep),
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
    synthesize: bool = False


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


_RELAY_KEYS = ("peer", "status", "answer", "acl_filtered", "audit_id", "path", "attenuated",
               "effective_roles", "latency_ms", "error")
_TRACE_KEYS = ("step", "kind", "agent", "path", "status", "latency_ms", "acl_filtered", "audit_id",
               "attenuated", "effective_roles", "error")


def _public_peer(name: str, res: dict) -> dict:
    meta = res.get("metadata") or {}
    return {
        "peer": name,
        "status": res.get("status", "unknown"),
        "answer": res.get("answer") or "",
        "acl_filtered": meta.get("acl_filtered"),
        "audit_id": meta.get("audit_id"),
        "error": res.get("error") if res.get("status") not in ("completed", "input-required") else None,
        "latency_ms": res.get("latency_ms"),
        "relayed": [{k: r.get(k) for k in _RELAY_KEYS} for r in (meta.get("relayed") or [])],
    }


def _check_gov_limit(request: Request) -> None:
    if not _gov_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="操作回数の上限に達しました。しばらくしてからお試しください")


@router.get("/api/a2a/demo/peers")
def demo_list_peers(persona: str | None = None, bridge: BridgeRuntime = Depends(get_bridge)):
    if bridge.demo is None or not bridge.a2a.enabled:
        return {"enabled": False, "agent": "", "peers": []}
    principal = _persona(bridge.demo, persona).principal if persona else None
    bridge.a2a.maybe_expire_governance()
    return {
        "enabled": True,
        "agent_id": bridge.a2a.agent_id,
        "governance_expires_in": bridge.a2a.governance_expires_in(),
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
    bridge.a2a.maybe_expire_governance()
    base_url = str(request.base_url).rstrip("/")
    card = bridge.a2a.agent_card(base_url=base_url)
    return {
        "agent": bridge.a2a.agent_name,
        "agent_id": bridge.a2a.agent_id,
        "max_hops": bridge.a2a.max_hops,
        "governance_ttl_sec": bridge.a2a.governance_ttl_sec,
        "governance_expires_in": bridge.a2a.governance_expires_in(),
        "description": bridge.a2a.agent_description,
        "discoverable": bridge.a2a.discoverable,
        "well_known_path": "/.well-known/agent.json",
        "agent_card": card,
        "yaml_snippet": (
            "a2a:\n"
            f"  enabled: true\n"
            f"  id: {bridge.a2a.agent_id}\n"
            f"  max_hops: {bridge.a2a.max_hops}\n"
            f"  discoverable: {'true' if bridge.a2a.discoverable else 'false'}\n"
            f"  name: \"{bridge.a2a.agent_name}\"\n"
            "  peers:\n"
            + "\n".join(
                f"    - name: {p.name}\n"
                f"      status: {p.status}\n"
                f"      allowed_roles: [{', '.join(sorted(p.allowed_roles))}]\n"
                f"      inbound_user_id: {p.inbound_user_id or '(未設定)'}\n"
                + (f"      relay_to: [{', '.join(p.relay_to)}]\n" if p.relay_to else "")
                + (f"      relay_roles: [{', '.join(p.relay_roles)}]\n" if p.relay_roles else "")
                + f"      api_key: \"${{A2A_KEY_{p.name.upper()}}}\""
                for p in bridge.a2a.peers.values()
            )
        ),
        "peers": bridge.a2a.peer_summary(principal),
        "incoming_invitations": bridge.a2a.list_incoming_invitations(),
    }


@router.post("/api/a2a/demo/publish")
def demo_toggle_publish(
    body: DemoPublishRequest,
    request: Request,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    _check_gov_limit(request)
    bridge.a2a.set_discoverable(body.discoverable)
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
    _check_gov_limit(request)  # 相手への外向き HTTP を伴うため回数を絞る
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
    request: Request,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    _check_gov_limit(request)
    if body.action == "invite":
        try:
            res = await bridge.a2a.send_peer_invitation(peer_name)
        except KeyError:
            raise HTTPException(status_code=404, detail="unknown peer") from None
        except ValueError as e:
            raise HTTPException(status_code=409, detail=str(e)) from None
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
    request: Request,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    _check_gov_limit(request)
    try:
        res = await bridge.a2a.respond_to_invitation(invite_code, body.decision)
    except KeyError:
        raise HTTPException(status_code=404, detail="unknown invitation") from None
    except ValueError as e:
        raise HTTPException(status_code=409, detail=str(e)) from None
    return {
        **res,
        "peers": bridge.a2a.peer_summary(),
        "incoming_invitations": bridge.a2a.list_incoming_invitations(),
    }


@router.post("/api/a2a/demo/verify-auth")
async def demo_verify_auth(
    body: DemoVerifyAuthRequest,
    request: Request,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    _check_gov_limit(request)
    try:
        return await bridge.a2a.verify_peer_auth(body.peer, mode=body.mode)
    except KeyError:
        raise HTTPException(status_code=404, detail=f"unknown peer: {body.peer}") from None
    except Exception as exc:
        log_upstream("demo a2a verify-auth failed", exc)
        raise HTTPException(status_code=502, detail="Peer への認証疎通テストに失敗しました") from None


@router.post("/api/a2a/demo/reset")
def demo_reset_governance(
    request: Request,
    _: DemoGateway = Depends(_demo_dep),
    bridge: BridgeRuntime = Depends(get_bridge),
):
    _check_gov_limit(request)
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
    bridge.a2a.maybe_expire_governance()
    # LLM はローカル1回 + 実際に委譲する(連携中かつ委譲上限内の)Peer ごとに1回 + 統合1回。
    # 比較ボタンと同じ予算から消費する。中継先の消費は中継先の Peer 別上限で絞られる
    calls = 1 + sum(1 for p in bridge.a2a.peers.values() if p.status == "active" and p.allows(principal))
    calls += 1 if body.synthesize else 0
    ip = client_ip(request)
    if not all(demo.ask_limiter.allow(ip) for _ in range(calls)):
        raise HTTPException(status_code=429, detail="AI回答の利用回数の上限に達しました。しばらくしてからお試しください")
    # ペルソナは全訪問者で共有するため、推測できないセッションを毎回発行して終了後に破棄する
    session_id = f"demo-a2a-{uuid.uuid4().hex}"
    try:
        res = await bridge.a2a.federated_ask(principal, body.question, session_id=session_id,
                                             synthesize=body.synthesize)
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
        "trace": [{k: t.get(k) for k in _TRACE_KEYS} for t in res.get("trace") or []],
        "synthesis": ({"answer": res["synthesis"]["answer"], "latency_ms": res["synthesis"]["latency_ms"]}
                      if res.get("synthesis") else None),
    }


@router.get("/api/a2a/demo/topology")
def demo_topology(request: Request, demo: DemoGateway = Depends(_demo_dep),
                  bridge: BridgeRuntime = Depends(get_bridge)):
    if not demo.read_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます")
    bridge.a2a.maybe_expire_governance()
    return bridge.a2a.topology()


@router.get("/api/a2a/demo/inbound-log")
def demo_inbound_log(request: Request, demo: DemoGateway = Depends(_demo_dep),
                     bridge: BridgeRuntime = Depends(get_bridge)):
    if not demo.read_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="リクエストが多すぎます")
    return {"agent_id": bridge.a2a.agent_id, "items": bridge.a2a.inbound_log(limit=15)}


class DemoAclProbeRequest(BaseModel):
    peer: str = Field(min_length=1, max_length=50)


@router.post("/api/a2a/demo/acl-probe")
async def demo_acl_probe(body: DemoAclProbeRequest, request: Request,
                         demo: DemoGateway = Depends(_demo_dep),
                         bridge: BridgeRuntime = Depends(get_bridge)):
    """機密狙いの質問は設定済みの固定文だけ(訪問者は文面を選べない)。Peer キーは Bridge の外に出さない。"""
    if not demo.ask_limiter.allow(client_ip(request)):
        raise HTTPException(status_code=429, detail="AI回答の利用回数の上限に達しました。しばらくしてからお試しください")
    try:
        return await bridge.a2a.acl_probe(body.peer)
    except KeyError:
        raise HTTPException(status_code=404, detail="この Peer には ACL 検証が設定されていません") from None
