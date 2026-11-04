"""
Principal(呼び出し主体)の解決と、文書ACLとの照合。

認証モード(profile の auth.mode):
  - api_key        : X-AISB-Key / Authorization: Bearer のキーで principal を引く(推奨)
  - trusted_header : 前段ゲートウェイ(SSO/リバースプロキシ)が付与する X-AISB-User/Tenant/
                     Roles/Depts をそのまま信用する。ゲートウェイ配下でのみ使うこと。
  - none           : 全員匿名。ACL未設定(public)の文書だけが見える。

照合ルール(default deny):
  - tenant : 文書に tenant があれば principal.tenant と一致必須(管理者も越境不可)
  - roles  : 文書に roles があれば principal.roles と1つ以上一致
  - depts  : 文書に depts があれば principal.depts と1つ以上一致
             (principal が "dept:*" ロールを持つ場合のみ部門制限を免除)
"""
from __future__ import annotations

import hmac
from dataclasses import dataclass

from fastapi import HTTPException, Request

from app.bridge.models import DocAcl

ADMIN_ROLE = "bridge_admin"
ALL_DEPTS_ROLE = "dept:*"


@dataclass(frozen=True)
class Principal:
    user_id: str
    tenant: str | None = None
    roles: tuple[str, ...] = ()
    depts: tuple[str, ...] = ()

    @property
    def is_admin(self) -> bool:
        return ADMIN_ROLE in self.roles

    def to_json(self) -> dict:
        return {"user_id": self.user_id, "tenant": self.tenant, "roles": list(self.roles), "depts": list(self.depts)}


ANONYMOUS = Principal(user_id="anonymous")


def can_read(p: Principal, acl: DocAcl) -> bool:
    if acl.tenant is not None and acl.tenant != p.tenant:
        return False
    if acl.roles and not set(acl.roles) & set(p.roles):
        return False
    if acl.depts and ALL_DEPTS_ROLE not in p.roles and not set(acl.depts) & set(p.depts):
        return False
    return True


def _split(v: str | None) -> tuple[str, ...]:
    return tuple(x.strip() for x in (v or "").split(",") if x.strip())


class PrincipalResolver:
    def __init__(self, auth_cfg: dict | None):
        cfg = auth_cfg or {}
        self.mode: str = cfg.get("mode", "none")
        if self.mode not in ("none", "api_key", "trusted_header"):
            raise ValueError(f"unknown auth.mode: {self.mode}")
        self._keys: dict[str, Principal] = {}
        for entry in cfg.get("api_keys", []) or []:
            key = entry.get("key")
            if not key:
                continue
            self._keys[key] = Principal(
                user_id=str(entry["user_id"]),
                tenant=entry.get("tenant"),
                roles=tuple(entry.get("roles") or ()),
                depts=tuple(entry.get("depts") or ()),
            )

    def resolve(self, request: Request) -> Principal:
        h = request.headers
        if self.mode == "none":
            return ANONYMOUS
        if self.mode == "trusted_header":
            user = h.get("x-aisb-user")
            if not user:
                return ANONYMOUS
            return Principal(user, h.get("x-aisb-tenant") or None, _split(h.get("x-aisb-roles")), _split(h.get("x-aisb-depts")))
        # api_key
        key = h.get("x-aisb-key") or ""
        auth = h.get("authorization") or ""
        if not key and auth.lower().startswith("bearer "):
            key = auth[7:].strip()
        if not key:
            return ANONYMOUS
        for k, p in self._keys.items():
            if hmac.compare_digest(k.encode(), key.encode()):
                return p
        raise HTTPException(status_code=401, detail="invalid API key")


def require_admin(p: Principal) -> None:
    if not p.is_admin:
        raise HTTPException(status_code=403, detail=f"role '{ADMIN_ROLE}' required")
