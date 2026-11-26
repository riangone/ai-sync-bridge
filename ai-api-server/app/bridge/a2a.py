"""
A2A (Agent-to-Agent) Adapter for AI-Sync Bridge.

Exposes each BridgeRuntime instance as an opaque, permission-bounded A2A Agent:
  - Agent Card discovery (`/.well-known/agent.json`)
  - JSON-RPC 2.0 task lifecycle (`tasks/send`, `tasks/get`, `tasks/cancel`)
  - Task states: submitted -> working -> input-required / completed / failed / canceled
  - Peer delegation (`A2APeerClient`) & cross-system federated Q&A (`federated_ask`)
  - Full hash-chained audit logging for inbound & outbound agent interactions
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx

from app.bridge.acl import Principal

if TYPE_CHECKING:
    from app.bridge.runtime import BridgeRuntime

log = logging.getLogger(__name__)

A2A_PROTOCOL_VERSION = "0.2.0"

# JSON-RPC 2.0 standard error codes
ERR_PARSE = -32700
ERR_INVALID_REQUEST = -32600
ERR_METHOD_NOT_FOUND = -32601
ERR_INVALID_PARAMS = -32602
ERR_INTERNAL = -32603
ERR_TASK_NOT_FOUND = -32001
ERR_FORBIDDEN = -32003


@dataclass
class PeerConfig:
    name: str
    url: str
    api_key: str = ""
    description: str = ""
    timeout_sec: float = 30.0
    # 委譲の上限(呼び出し側の方針): このロールのいずれかを持つ主体だけがこのPeerへ委譲できる。
    # 空なら誰でも委譲可。Peer 側の ACL はキーに紐づく Agent 主体で別途かかる(二重の境界)。
    allowed_roles: frozenset[str] = frozenset()
    # 連携ライフサイクル状態: active | invited | rejected | blocked
    status: str = "active"
    invite_code: str = ""

    def allows(self, principal: Principal) -> bool:
        return not self.allowed_roles or bool(self.allowed_roles & set(principal.roles))


@dataclass
class IncomingInvitation:
    invite_code: str
    from_agent: str
    from_peer_name: str
    status: str = "pending"  # pending | approved | rejected
    note: str = ""
    created_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "invite_code": self.invite_code,
            "from_agent": self.from_agent,
            "from_peer_name": self.from_peer_name,
            "status": self.status,
            "note": self.note,
            "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.created_at)),
        }


@dataclass
class A2ATask:
    id: str
    session_id: str
    owner_user_id: str
    state: str = "submitted"
    message: dict[str, Any] | None = None
    history: list[dict[str, Any]] = field(default_factory=list)
    artifacts: list[dict[str, Any]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    created_at: float = field(default_factory=time.time)
    updated_at: float = field(default_factory=time.time)

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "sessionId": self.session_id,
            "status": {
                "state": self.state,
                "message": self.message,
                "timestamp": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(self.updated_at)),
            },
            "history": self.history,
            "artifacts": self.artifacts,
            "metadata": self.metadata,
        }


def _extract_text(message: dict[str, Any] | None) -> str:
    if not isinstance(message, dict):
        return ""
    parts = message.get("parts") or []
    texts: list[str] = []
    for p in parts:
        if isinstance(p, dict) and p.get("type") == "text" and isinstance(p.get("text"), str):
            texts.append(p["text"].strip())
    return "\n".join(t for t in texts if t).strip()


def _agent_message(text: str) -> dict[str, Any]:
    return {"role": "agent", "parts": [{"type": "text", "text": text}]}


def _rpc_ok(req_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": req_id, "result": result}


def _rpc_err(req_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    err: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


class A2AAdapter:
    """Wraps a BridgeRuntime to speak the A2A protocol and delegate to peer agents."""

    def __init__(self, runtime: "BridgeRuntime", cfg: dict[str, Any] | None = None):
        cfg = cfg or {}
        self.runtime = runtime
        self.enabled: bool = bool(cfg.get("enabled", True))
        self.discoverable: bool = bool(cfg.get("discoverable", True))
        self._initial_discoverable: bool = self.discoverable
        self.agent_name: str = str(cfg.get("name") or "AI-Sync Bridge Agent")
        self.agent_description: str = str(
            cfg.get("description")
            or "Opaque, ACL-enforced legacy system agent powered by AI-Sync Bridge."
        )
        self.public_url: str = str(cfg.get("url") or "http://localhost:5011").rstrip("/")
        self.provider_org: str = str(cfg.get("organization") or "AI-Sync Bridge")
        self.custom_skills: list[dict[str, Any]] = list(cfg.get("skills") or [])
        self.peers: dict[str, PeerConfig] = {}
        for p in cfg.get("peers") or []:
            if not p.get("name") or not p.get("url"):
                continue
            self.peers[p["name"]] = PeerConfig(
                name=str(p["name"]),
                url=str(p["url"]).rstrip("/"),
                api_key=str(p.get("api_key") or ""),
                description=str(p.get("description") or ""),
                timeout_sec=float(p.get("timeout_sec") or 30.0),
                allowed_roles=frozenset(str(r) for r in (p.get("allowed_roles") or ())),
            )
        self._initial_peer_names: set[str] = set(self.peers.keys())
        self.incoming_invitations: dict[str, IncomingInvitation] = {}
        self._tasks: dict[str, A2ATask] = {}
        self._max_tasks = 500
        # 外向き HTTP の差し替え口(テストや同一プロセス内の Peer で ASGITransport を渡す)
        self.transport: httpx.AsyncBaseTransport | None = None

    # ---------------- Agent Card ----------------
    def agent_card(self, base_url: str | None = None) -> dict[str, Any]:
        url = (base_url or self.public_url).rstrip("/")
        skills = list(self.custom_skills)
        if not skills:
            for src_name, src in self.runtime.sources.items():
                for spec in src.entities:
                    skills.append({
                        "id": f"query_{spec.name.lower()}",
                        "name": f"Query {spec.name}",
                        "description": f"Permission-bounded search & grounded Q&A over {spec.name} ({spec.label or src_name}).",
                        "tags": [src_name, spec.name.lower()],
                    })
        return {
            "name": self.agent_name,
            "description": self.agent_description,
            "url": f"{url}/a2a",
            "version": A2A_PROTOCOL_VERSION,
            "provider": {"organization": self.provider_org},
            "capabilities": {
                "streaming": False,
                "pushNotifications": False,
                "stateTransitionHistory": True,
            },
            "authentication": {
                "schemes": ["Bearer", "ApiKey"],
                "credentials": "X-AISB-Key or Authorization: Bearer <key>",
            },
            "defaultInputModes": ["text/plain"],
            "defaultOutputModes": ["text/plain", "application/json"],
            "skills": skills,
        }

    # ---------------- JSON-RPC 2.0 Dispatcher ----------------
    async def handle_rpc(self, principal: Principal, payload: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(payload, dict) or payload.get("jsonrpc") != "2.0":
            return _rpc_err(None, ERR_INVALID_REQUEST, "Invalid JSON-RPC 2.0 request")
        req_id = payload.get("id")
        method = payload.get("method")
        params = payload.get("params") or {}
        if not isinstance(params, dict):
            return _rpc_err(req_id, ERR_INVALID_PARAMS, "params must be an object")

        if method == "tasks/send":
            return await self._handle_tasks_send(req_id, principal, params)
        if method == "tasks/get":
            return self._handle_tasks_get(req_id, principal, params)
        if method == "tasks/cancel":
            return self._handle_tasks_cancel(req_id, principal, params)
        return _rpc_err(req_id, ERR_METHOD_NOT_FOUND, f"Unknown method: {method}")

    async def _handle_tasks_send(self, req_id: Any, principal: Principal, params: dict[str, Any]) -> dict[str, Any]:
        task_id = str(params.get("id") or uuid.uuid4().hex)
        session_id = str(params.get("sessionId") or f"a2a:{task_id}")
        message = params.get("message")
        text = _extract_text(message)
        metadata = dict(params.get("metadata") or {})
        entities = metadata.get("entities")
        top_k = metadata.get("top_k")

        task = self._tasks.get(task_id)
        if task is not None and task.owner_user_id != principal.user_id and not principal.is_admin:
            return _rpc_err(req_id, ERR_FORBIDDEN, "Task belongs to another principal")

        if task is None:
            task = A2ATask(id=task_id, session_id=session_id, owner_user_id=principal.user_id)
            self._store_task(task)

        if message:
            task.history.append(message)

        if not text:
            task.state = "input-required"
            task.message = _agent_message("Please provide a non-empty text query in message.parts.")
            task.updated_at = time.time()
            return _rpc_ok(req_id, task.to_dict())

        task.state = "working"
        task.updated_at = time.time()
        self.runtime.audit.append(
            "a2a.task.received",
            principal.user_id,
            detail={
                "task_id": task_id,
                "session_id": session_id,
                "query_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "principal": principal.to_json(),
                # 呼び出し元 Agent が申告した利用者。追跡用の情報で、権限判定には使わない
                "on_behalf_of": str(metadata.get("on_behalf_of") or "")[:64] or None,
            },
        )

        try:
            if self.runtime.answerer.enabled:
                res = await self.runtime.ask(
                    principal=principal,
                    question=text,
                    session_id=session_id,
                    top_k=top_k,
                    entities=entities,
                )
                answer_text = res.get("answer") or ""
                citations = res.get("citations") or []
                acl_filtered = res.get("acl_filtered", 0)
                audit_id = res.get("audit_id") or res.get("retrieval_audit_id")
                if res.get("unanswered") and metadata.get("require_grounding"):
                    task.state = "input-required"
                    task.message = _agent_message(
                        answer_text or "No authorized records matched. Please provide an order ID or customer code."
                    )
                else:
                    task.state = "completed"
                    task.message = _agent_message(answer_text)
                artifact_data = {
                    "answer": answer_text,
                    "citations": citations,
                    "acl_filtered": acl_filtered,
                    "audit_id": audit_id,
                    "unanswered": bool(res.get("unanswered", False)),
                }
            else:
                res = await self.runtime.search(
                    principal=principal,
                    query=text,
                    top_k=top_k or 5,
                    entities=entities,
                )
                results = res.get("results") or []
                if not results:
                    summary = "No authorized records matched your query."
                    task.state = "input-required" if metadata.get("require_grounding") else "completed"
                else:
                    lines = [f"- [{r['entity']}/{r['pk']}] {r['title']}: {r['snippet']}" for r in results]
                    summary = "\n".join(lines)
                    task.state = "completed"
                task.message = _agent_message(summary)
                artifact_data = {
                    "results": results,
                    "acl_filtered": res.get("acl_filtered", 0),
                    "audit_id": res.get("audit_id"),
                }

            task.history.append(task.message)
            task.artifacts = [
                {
                    "name": "bridge_response",
                    "parts": [
                        {"type": "text", "text": _extract_text(task.message)},
                        {"type": "data", "data": artifact_data},
                    ],
                }
            ]
            task.metadata = {
                "agent": self.agent_name,
                "acl_filtered": artifact_data.get("acl_filtered", 0),
                "audit_id": artifact_data.get("audit_id"),
            }
            task.updated_at = time.time()
            self.runtime.audit.append(
                "a2a.task.completed",
                principal.user_id,
                detail={
                    "task_id": task_id,
                    "state": task.state,
                    "acl_filtered": artifact_data.get("acl_filtered", 0),
                    "audit_id": artifact_data.get("audit_id"),
                },
            )
            return _rpc_ok(req_id, task.to_dict())
        except Exception as exc:
            task.state = "failed"
            task.message = _agent_message(f"Task execution failed: {type(exc).__name__}")
            task.updated_at = time.time()
            self.runtime.audit.append(
                "a2a.task.failed",
                principal.user_id,
                detail={"task_id": task_id, "error": type(exc).__name__},
            )
            return _rpc_ok(req_id, task.to_dict())

    def _handle_tasks_get(self, req_id: Any, principal: Principal, params: dict[str, Any]) -> dict[str, Any]:
        task_id = params.get("id")
        if not task_id or task_id not in self._tasks:
            return _rpc_err(req_id, ERR_TASK_NOT_FOUND, f"Task not found: {task_id}")
        task = self._tasks[task_id]
        if task.owner_user_id != principal.user_id and not principal.is_admin:
            return _rpc_err(req_id, ERR_FORBIDDEN, "Task belongs to another principal")
        return _rpc_ok(req_id, task.to_dict())

    def _handle_tasks_cancel(self, req_id: Any, principal: Principal, params: dict[str, Any]) -> dict[str, Any]:
        task_id = params.get("id")
        if not task_id or task_id not in self._tasks:
            return _rpc_err(req_id, ERR_TASK_NOT_FOUND, f"Task not found: {task_id}")
        task = self._tasks[task_id]
        if task.owner_user_id != principal.user_id and not principal.is_admin:
            return _rpc_err(req_id, ERR_FORBIDDEN, "Task belongs to another principal")
        task.state = "canceled"
        task.message = _agent_message("Task canceled by caller.")
        task.updated_at = time.time()
        return _rpc_ok(req_id, task.to_dict())

    def _store_task(self, task: A2ATask) -> None:
        if len(self._tasks) >= self._max_tasks:
            oldest = min(self._tasks.values(), key=lambda t: t.updated_at)
            self._tasks.pop(oldest.id, None)
        self._tasks[task.id] = task

    # ---------------- Peer Discovery & Delegation ----------------
    async def discover_peer(self, peer_name: str, client: httpx.AsyncClient | None = None) -> dict[str, Any]:
        peer = self.peers.get(peer_name)
        if not peer:
            raise KeyError(f"Unknown A2A peer: {peer_name}")
        url = f"{peer.url}/.well-known/agent.json"
        if client is not None:
            resp = await client.get(url, timeout=peer.timeout_sec)
            resp.raise_for_status()
            return resp.json()
        async with httpx.AsyncClient(timeout=peer.timeout_sec, transport=self.transport) as c:
            resp = await c.get(url)
            resp.raise_for_status()
            return resp.json()

    async def delegate_to_peer(
        self,
        peer_name: str,
        question: str,
        *,
        session_id: str | None = None,
        metadata: dict[str, Any] | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        peer = self.peers.get(peer_name)
        if not peer:
            raise KeyError(f"Unknown A2A peer: {peer_name}")
        task_id = uuid.uuid4().hex
        rpc_body = {
            "jsonrpc": "2.0",
            "id": task_id,
            "method": "tasks/send",
            "params": {
                "id": task_id,
                "sessionId": session_id or f"fed:{task_id}",
                "message": {"role": "user", "parts": [{"type": "text", "text": question}]},
                "metadata": metadata or {},
            },
        }
        headers = {"Content-Type": "application/json"}
        if peer.api_key:
            headers["Authorization"] = f"Bearer {peer.api_key}"
        endpoint = f"{peer.url}/a2a"
        if client is not None:
            resp = await client.post(endpoint, json=rpc_body, headers=headers, timeout=peer.timeout_sec)
            resp.raise_for_status()
            return resp.json()
        async with httpx.AsyncClient(timeout=peer.timeout_sec, transport=self.transport) as c:
            resp = await c.post(endpoint, json=rpc_body, headers=headers)
            resp.raise_for_status()
            return resp.json()

    async def federated_ask(
        self,
        principal: Principal,
        question: str,
        *,
        peers: list[str] | None = None,
        session_id: str = "federated",
        top_k: int | None = None,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Run local ACL-bounded Bridge Q&A and delegate in parallel to selected A2A peers."""
        target_peers = [p for p in (peers if peers is not None else list(self.peers.keys())) if p in self.peers]

        async def _local():
            if self.runtime.answerer.enabled:
                return await self.runtime.ask(principal, question, session_id=session_id, top_k=top_k)
            return await self.runtime.search(principal, question, top_k=top_k or 5)

        async def _call_peer(name: str) -> tuple[str, dict[str, Any]]:
            peer = self.peers[name]
            if peer.status == "blocked":
                return name, {"status": "blocked", "error": "peer is blocked by local governance policy"}
            if peer.status != "active":
                return name, {"status": peer.status, "error": f"peer is {peer.status} (not active)"}
            if not peer.allows(principal):
                return name, {"status": "forbidden", "error": "delegation not permitted for this principal"}
            try:
                rpc_res = await self.delegate_to_peer(
                    name, question, session_id=session_id, client=client,
                    metadata={"on_behalf_of": principal.user_id},
                )
                if "error" in rpc_res:
                    return name, {"status": "error", "error": (rpc_res["error"] or {}).get("message", "error")}
                result = rpc_res.get("result") or {}
                status = (result.get("status") or {}).get("state", "unknown")
                msg_text = _extract_text((result.get("status") or {}).get("message"))
                return name, {
                    "status": status,
                    "task_id": result.get("id"),
                    "answer": msg_text,
                    "metadata": result.get("metadata") or {},
                }
            except Exception as exc:
                # 接続先URLや内部構成を含み得るため、詳細はログにだけ残す
                log.warning("A2A peer %s failed: %s", name, exc)
                if isinstance(exc, httpx.HTTPStatusError):
                    return name, {"status": "error", "error": f"peer returned HTTP {exc.response.status_code}"}
                return name, {"status": "unreachable", "error": type(exc).__name__}

        local_coro = _local()
        peer_coros = [_call_peer(name) for name in target_peers]
        local_res, *peer_pairs = await asyncio.gather(local_coro, *peer_coros)
        peer_results = dict(peer_pairs)

        self.runtime.audit.append(
            "a2a.delegated",
            principal.user_id,
            detail={
                "peers": target_peers,
                "peer_statuses": {k: v.get("status") for k, v in peer_results.items()},
                "query_sha256": hashlib.sha256(question.encode("utf-8")).hexdigest(),
            },
        )
        return {
            "question": question,
            "agent": self.agent_name,
            "local": local_res,
            "peers": peer_results,
        }

    # ---------------- Governance & Real Mutual Invitation ----------------
    def _self_peer_key(self) -> str:
        low = self.agent_name.lower()
        if "crm" in low:
            return "crm"
        if "erp" in low:
            return "erp"
        return low.split()[0] if low else "agent"

    def peer_summary(self, principal: Principal | None = None) -> list[dict[str, Any]]:
        return [
            {
                "name": p.name,
                "description": p.description,
                "status": p.status,
                "allowed_roles": sorted(p.allowed_roles),
                "allowed": (principal is None or p.allows(principal)) and p.status == "active",
                "role_allowed": principal is None or p.allows(principal),
                "auth_configured": bool(p.api_key),
                "invite_code": p.invite_code,
            }
            for p in self.peers.values()
        ]

    def list_incoming_invitations(self) -> list[dict[str, Any]]:
        invs = sorted(self.incoming_invitations.values(), key=lambda x: x.created_at, reverse=True)
        return [inv.to_dict() for inv in invs]

    def set_peer_status(self, peer_name: str, status: str) -> PeerConfig:
        if status not in ("active", "invited", "rejected", "blocked"):
            raise ValueError(f"Unsupported peer status: {status}")
        peer = self.peers.get(peer_name)
        if not peer:
            raise KeyError(f"Unknown A2A peer: {peer_name}")
        peer.status = status
        if status == "invited" and not peer.invite_code:
            peer.invite_code = f"inv_{uuid.uuid4().hex[:10]}"
        elif status == "active":
            peer.invite_code = ""
        self.runtime.audit.append(
            "a2a.governance.status_changed",
            "demo-governance",
            detail={"peer": peer_name, "status": status},
        )
        return peer

    async def send_peer_invitation(
        self,
        peer_name: str,
        note: str = "",
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Send a real authenticated A2A invitation to a configured peer system."""
        peer = self.peers.get(peer_name)
        if not peer:
            raise KeyError(f"Unknown A2A peer: {peer_name}")
        code = f"inv_{uuid.uuid4().hex[:10]}"
        peer.status = "invited"
        peer.invite_code = code

        payload = {
            "invite_code": code,
            "from_agent": self.agent_name,
            "from_peer_name": self._self_peer_key(),
            "note": note or f"{self.agent_name} からの A2A 連携招待リクエスト",
        }
        headers = {"Content-Type": "application/json"}
        if peer.api_key:
            headers["Authorization"] = f"Bearer {peer.api_key}"
        endpoint = f"{peer.url}/a2a/invitations"

        delivered = False
        remote_status = 0
        try:
            if client is not None:
                resp = await client.post(endpoint, json=payload, headers=headers, timeout=peer.timeout_sec)
            else:
                async with httpx.AsyncClient(timeout=peer.timeout_sec, transport=self.transport) as c:
                    resp = await c.post(endpoint, json=payload, headers=headers)
            remote_status = resp.status_code
            delivered = resp.status_code == 200
        except Exception as exc:
            log.warning("A2A invitation send to %s failed: %s", peer_name, exc)

        self.runtime.audit.append(
            "a2a.governance.invitation_sent",
            "demo-governance",
            detail={"peer": peer_name, "invite_code": code, "delivered": delivered, "remote_status": remote_status},
        )
        return {
            "peer": peer.name,
            "status": peer.status,
            "invite_code": code,
            "delivered": delivered,
            "remote_status": remote_status,
        }

    def receive_invitation(
        self,
        *,
        invite_code: str,
        from_agent: str,
        from_peer_name: str,
        note: str = "",
    ) -> IncomingInvitation:
        inv = IncomingInvitation(
            invite_code=invite_code,
            from_agent=from_agent,
            from_peer_name=from_peer_name,
            status="pending",
            note=note,
        )
        self.incoming_invitations[invite_code] = inv
        self.runtime.audit.append(
            "a2a.governance.invitation_received",
            from_peer_name,
            detail={"invite_code": invite_code, "from_agent": from_agent},
        )
        return inv

    async def respond_to_invitation(
        self,
        invite_code: str,
        decision: str,
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Approve or reject an incoming invitation and notify the sender agent over HTTP."""
        if decision not in ("approve", "reject"):
            raise ValueError(f"Unsupported decision: {decision}")
        inv = self.incoming_invitations.get(invite_code)
        if not inv:
            raise KeyError(f"Unknown invitation: {invite_code}")
        inv.status = "approved" if decision == "approve" else "rejected"

        peer = self.peers.get(inv.from_peer_name)
        callback_delivered = False
        callback_status = 0
        if peer is not None:
            peer.status = "active" if decision == "approve" else "rejected"
            if decision == "approve":
                peer.invite_code = ""
            headers = {"Content-Type": "application/json"}
            if peer.api_key:
                headers["Authorization"] = f"Bearer {peer.api_key}"
            endpoint = f"{peer.url}/a2a/invitations/{invite_code}/decision"
            payload = {"decision": inv.status, "from_agent": self.agent_name}
            try:
                if client is not None:
                    resp = await client.post(endpoint, json=payload, headers=headers, timeout=peer.timeout_sec)
                else:
                    async with httpx.AsyncClient(timeout=peer.timeout_sec, transport=self.transport) as c:
                        resp = await c.post(endpoint, json=payload, headers=headers)
                callback_status = resp.status_code
                callback_delivered = resp.status_code == 200
            except Exception as exc:
                log.warning("A2A invitation decision callback to %s failed: %s", peer.name, exc)

        self.runtime.audit.append(
            "a2a.governance.invitation_responded",
            "demo-governance",
            detail={
                "invite_code": invite_code,
                "decision": inv.status,
                "from_peer": inv.from_peer_name,
                "callback_delivered": callback_delivered,
            },
        )
        return {
            "invitation": inv.to_dict(),
            "callback_delivered": callback_delivered,
            "callback_status": callback_status,
        }

    def receive_invitation_decision(
        self,
        *,
        invite_code: str,
        decision: str,
        from_agent: str = "",
    ) -> PeerConfig | None:
        target_status = "active" if decision == "approved" else "rejected"
        matched: PeerConfig | None = None
        for p in self.peers.values():
            if p.invite_code == invite_code:
                matched = p
                break
        if matched is not None:
            matched.status = target_status
            if target_status == "active":
                matched.invite_code = ""
        self.runtime.audit.append(
            "a2a.governance.invitation_decision_received",
            from_agent or "peer",
            detail={
                "invite_code": invite_code,
                "decision": decision,
                "matched_peer": matched.name if matched else None,
            },
        )
        return matched

    def reset_governance_demo(self) -> None:
        self.discoverable = self._initial_discoverable
        self.incoming_invitations.clear()
        for name in list(self.peers.keys()):
            if name not in self._initial_peer_names:
                self.peers.pop(name, None)
            else:
                self.peers[name].status = "active"
                self.peers[name].invite_code = ""
        self.runtime.audit.append("a2a.governance.reset", "demo-governance", detail={})

    async def verify_peer_auth(
        self,
        peer_name: str,
        mode: str = "valid",
        client: httpx.AsyncClient | None = None,
    ) -> dict[str, Any]:
        """Real authentication probe against a configured peer's /a2a endpoint (no LLM call)."""
        peer = self.peers.get(peer_name)
        if not peer:
            raise KeyError(f"Unknown A2A peer: {peer_name}")
        rpc_body = {
            "jsonrpc": "2.0",
            "id": f"auth-probe-{uuid.uuid4().hex[:6]}",
            "method": "tasks/get",
            "params": {"id": "auth-probe-nonexistent"},
        }
        headers = {"Content-Type": "application/json"}
        if mode == "valid":
            if peer.api_key:
                headers["Authorization"] = f"Bearer {peer.api_key}"
            header_sent = "Authorization: Bearer <env:A2A_PEER_KEY (マスク済)>"
        elif mode == "invalid":
            headers["Authorization"] = "Bearer invalid-demo-key-0000"
            header_sent = "Authorization: Bearer invalid-demo-key-0000"
        else:
            header_sent = "(認証ヘッダなし / 匿名)"

        endpoint = f"{peer.url}/a2a"
        if client is not None:
            resp = await client.post(endpoint, json=rpc_body, headers=headers, timeout=peer.timeout_sec)
        else:
            async with httpx.AsyncClient(timeout=peer.timeout_sec, transport=self.transport) as c:
                resp = await c.post(endpoint, json=rpc_body, headers=headers)

        try:
            body = resp.json()
        except Exception:
            body = {"raw": resp.text[:200]}

        authenticated = resp.status_code == 200
        if authenticated:
            summary = "HTTP 200: 認証成功（Peer専用キーで最小権限Agent主体にマッピングされ、JSON-RPC層へ到達）"
        elif resp.status_code == 401:
            summary = f"HTTP 401: 認証拒否（{body.get('detail', 'API key required')} — 匿名・不正キーは即座に遮断）"
        else:
            summary = f"HTTP {resp.status_code}: {body}"

        return {
            "peer": peer.name,
            "mode": mode,
            "http_status": resp.status_code,
            "authenticated": authenticated,
            "header_sent": header_sent,
            "response_excerpt": body,
            "summary": summary,
        }
