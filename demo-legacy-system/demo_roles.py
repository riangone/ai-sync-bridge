"""
公開デモの「ロールを選んで入る」入口と、画面・JSON API の権限制御。

顧客の実システムなら既存のログインや SSO が担う部分を、デモ用に置き換えたもの。
パスワードはなく誰でも管理者を選べるため、これは認証ではない(データはすべて架空)。

権限の定義は aisb_profile/bridge.yaml の1か所だけに置く:
  - demo.personas                主体(AI パネルの権限検索と同じもの)
  - sources[].entities[].acl     取り込み対象の権限(検索結果の絞り込みと同じもの)
  - demo.screens                 取り込み対象ではない画面の権限
  - demo.screen_write_roles      閲覧より登録・編集を狭くする画面

不変条件:
  1. 定義のない画面は誰にも見せない(default deny)。
  2. リバースプロキシを経由しないサーバー内部の呼び出し(ブリッジの同期、API サーバーの
     データ取得、リセットスクリプト)は、Cookie がなければ制限しない。
  3. 照合ルールは ai-api-server/app/bridge/acl.py の can_read と揃える
     (tests/test_demo_roles.py の test_policy_matches_bridge_acl で一致を確認している)。
"""
from __future__ import annotations

import hashlib
import hmac
import secrets
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import yaml
from aisb_embed.routes import is_local_direct
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, RedirectResponse

ALL_DEPTS_ROLE = "dept:*"
COOKIE_NAME = "aisb_demo_role"
ROLE_PATH = "/role"
PUBLIC_PREFIXES = ("/static/", "/aisb-embed/")
WRITE_ACTIONS = ("Entry", "Register")

# (メニューのリンク先, 表示名, エンティティ)
NAV_ITEMS = (
    ("/Customer/List", "顧客管理", "Customer"),
    ("/Order/List", "受注管理", "Order"),
    ("/Estimate/List", "見積管理", "Estimate"),
    ("/Invoice/List", "請求管理", "Invoice"),
    ("/PurchaseOrder/List", "発注管理", "PurchaseOrder"),
    ("/Supplier/List", "仕入先管理", "Supplier"),
    ("/Employee/List", "従業員管理", "Employee"),
    ("/Product/Inquiry", "商品在庫照会", "Product"),
    ("/InventoryTransaction/List", "在庫トランザクション", "InventoryTransaction"),
    ("/GoodsReceipt/List", "入荷管理", "GoodsReceipt"),
    ("/Property/List", "物件管理", "Property"),
    ("/ArAp/List", "売掛買掛", "ArAp"),
    ("/Profit/List", "利益管理", "Profit"),
)
# URL の先頭セグメントとエンティティ名が異なるもの
_PATH_ALIASES = {"Stock": "Product"}
_ENTITIES = {entity for _, _, entity in NAV_ITEMS}


def _resolve(spec, row: dict | None):
    if isinstance(spec, str) and spec.startswith("$"):
        return None if row is None else row.get(spec[1:])
    return spec


def _as_set(value) -> set[str]:
    if value is None or value == "":
        return set()
    if isinstance(value, (list, tuple, set)):
        return {str(v) for v in value if v not in (None, "")}
    return {str(value)}


@dataclass(frozen=True)
class Persona:
    id: str
    label: str
    note: str
    description: str
    tenant: str | None
    roles: frozenset[str]
    depts: frozenset[str]
    panels: tuple[str, ...]
    selectable: bool


class RolePolicy:
    def __init__(self, profile: dict):
        demo = profile.get("demo") or {}
        self.personas = {
            p["id"]: Persona(
                id=p["id"], label=p.get("label", p["id"]), note=p.get("note", ""),
                description=p.get("description", ""), tenant=p.get("tenant"),
                roles=frozenset(p.get("roles") or ()), depts=frozenset(p.get("depts") or ()),
                panels=tuple(p.get("panels") or ("bridge",)), selectable=p.get("selectable", True),
            )
            for p in demo.get("personas") or []
        }
        self.acls: dict[str, dict] = {}
        for source in profile.get("sources") or []:
            for entity in source.get("entities") or []:
                self.acls[entity["name"]] = entity.get("acl") or {}
        self.acls.update(demo.get("screens") or {})
        self.write_roles = {k: set(v) for k, v in (demo.get("screen_write_roles") or {}).items()}

    def selectable(self) -> list[Persona]:
        return [p for p in self.personas.values() if p.selectable]

    def can_view(self, persona: Persona, entity: str) -> bool:
        """画面単位の判定。行ごとに決まる部署の条件は row_visible で見る。"""
        acl = self.acls.get(entity)
        return acl is not None and self._matches(persona, acl, None)

    def row_visible(self, persona: Persona, entity: str, row: dict) -> bool:
        acl = self.acls.get(entity)
        return acl is not None and self._matches(persona, acl, row)

    def can_write(self, persona: Persona, entity: str) -> bool:
        if not self.can_view(persona, entity):
            return False
        required = self.write_roles.get(entity)
        return required is None or bool(required & persona.roles)

    def visible_screens(self, persona: Persona) -> list[str]:
        return [label for _, label, entity in NAV_ITEMS if self.can_view(persona, entity)]

    @staticmethod
    def _matches(persona: Persona, acl: dict, row: dict | None) -> bool:
        tenant = _resolve(acl.get("tenant"), row)
        if tenant not in (None, "") and str(tenant) != persona.tenant:
            return False
        roles = _as_set(_resolve(acl.get("roles"), row))
        if roles and not roles & persona.roles:
            return False
        spec = acl.get("depts")
        if ALL_DEPTS_ROLE in persona.roles or (row is None and isinstance(spec, str) and spec.startswith("$")):
            return True
        depts = _as_set(_resolve(spec, row))
        return not depts or bool(depts & persona.depts)


def load_policy(path: Path | str) -> RolePolicy:
    with open(path, encoding="utf-8") as f:
        return RolePolicy(yaml.safe_load(f) or {})


def classify(path: str) -> tuple[str | None, bool]:
    """パスを (エンティティ, 登録・編集か) に分類する。業務画面でなければエンティティは None。"""
    parts = path.strip("/").split("/")
    if parts[0] == "api":
        return (parts[1] if len(parts) > 1 and parts[1] in _ENTITIES else None), False
    entity = _PATH_ALIASES.get(parts[0], parts[0])
    if entity not in _ENTITIES:
        return None, False
    return entity, len(parts) > 1 and parts[1] in WRITE_ACTIONS


def safe_next(value: str | None) -> str:
    """選択後の遷移先。自サイト内のパスだけを受け付ける(オープンリダイレクト防止)。"""
    if not value or not value.startswith("/") or value.startswith("//") or any(c in value for c in "\\\r\n"):
        return "/"
    parts = urlsplit(value)
    if parts.scheme or parts.netloc or parts.path == ROLE_PATH:
        return "/"
    return value


class DemoRoles:
    """リクエスト単位の判定をまとめた窓口。main.py とテンプレートはここだけを使う。"""

    def __init__(self, policy: RolePolicy):
        self.policy = policy
        # 署名鍵はプロセスごとに生成する。再起動でロールの選び直しになるだけで、保存する情報はない。
        self._secret = secrets.token_bytes(32)

    def sign(self, persona_id: str) -> str:
        sig = hmac.new(self._secret, persona_id.encode("utf-8"), hashlib.sha256).hexdigest()
        return f"{persona_id}.{sig}"

    def persona_from_cookie(self, request: Request) -> Persona | None:
        persona_id, _, _ = request.cookies.get(COOKIE_NAME, "").partition(".")
        persona = self.policy.personas.get(persona_id)
        if persona is None or not persona.selectable:
            return None
        if not hmac.compare_digest(request.cookies.get(COOKIE_NAME, ""), self.sign(persona_id)):
            return None
        return persona

    @staticmethod
    def current(request: Request) -> Persona | None:
        return getattr(request.state, "persona", None)

    # 以下は Persona がない場合(サーバー内部の呼び出し)は制限しない
    def can_view(self, request: Request, entity: str) -> bool:
        persona = self.current(request)
        return persona is None or self.policy.can_view(persona, entity)

    def can_write(self, request: Request, entity: str) -> bool:
        persona = self.current(request)
        return persona is None or self.policy.can_write(persona, entity)

    def row_visible(self, request: Request, entity: str, row: dict) -> bool:
        persona = self.current(request)
        return persona is None or self.policy.row_visible(persona, entity, row)

    def filter_rows(self, request: Request, entity: str, rows: list[dict]) -> list[dict]:
        return [r for r in rows if self.row_visible(request, entity, r)]

    def nav_items(self, request: Request) -> list[tuple[str, str, str]]:
        return [item for item in NAV_ITEMS if self.can_view(request, item[2])]

    def page_context(self, request: Request) -> dict | None:
        """ページと AI パネルに渡す現在のロール。ここに権限の詳細は含めない。"""
        persona = self.current(request)
        if persona is None:
            return None
        return {"id": persona.id, "label": persona.label, "note": persona.note, "panels": list(persona.panels)}


def install(app: FastAPI, templates, profile_path: Path | str) -> DemoRoles:
    roles = DemoRoles(load_policy(profile_path))
    templates.env.globals.update(
        demo_role=roles.page_context, nav_items=roles.nav_items, can_view=roles.can_view,
    )

    def prefix_of(request: Request) -> str:
        return request.headers.get("x-forwarded-prefix", "")

    @app.middleware("http")
    async def role_gate(request: Request, call_next):
        path = request.scope["path"]
        persona = roles.persona_from_cookie(request)
        request.state.persona = persona
        if path == ROLE_PATH or path.startswith(PUBLIC_PREFIXES):
            return await call_next(request)
        if persona is None:
            if is_local_direct(request):
                return await call_next(request)
            if path.startswith("/api/"):
                return JSONResponse({"detail": "ロールを選択してください"}, status_code=401)
            target = path + (f"?{request.url.query}" if request.url.query else "")
            query = urlencode({"next": safe_next(target)})
            return RedirectResponse(f"{prefix_of(request)}{ROLE_PATH}?{query}", status_code=303)

        entity, is_write = classify(path)
        if entity is not None:
            allowed = roles.policy.can_write(persona, entity) if is_write else roles.policy.can_view(persona, entity)
            if not allowed:
                if path.startswith("/api/"):
                    return JSONResponse({"detail": "このロールでは利用できません"}, status_code=403)
                return templates.TemplateResponse(
                    request, "role_forbidden.html", {"title": "権限がありません", "is_write": is_write}, status_code=403,
                )
        return await call_next(request)

    @app.get(ROLE_PATH)
    def role_select(request: Request):
        cards = [
            {"persona": p, "screens": roles.policy.visible_screens(p), "all_panels": "*" in p.panels}
            for p in roles.policy.selectable()
        ]
        return templates.TemplateResponse(request, "role_select.html", {
            "title": "ロール選択", "cards": cards, "next": safe_next(request.query_params.get("next")),
        })

    @app.post(ROLE_PATH)
    async def role_submit(request: Request):
        form = await request.form()
        persona = roles.policy.personas.get(str(form.get("persona", "")))
        if persona is None or not persona.selectable:
            return RedirectResponse(f"{prefix_of(request)}{ROLE_PATH}", status_code=303)
        # 選んだロールで開けない画面へは送らず、メニューから始めてもらう
        target = safe_next(str(form.get("next", "")))
        entity, is_write = classify(urlsplit(target).path)
        if entity is not None and not (roles.policy.can_write if is_write else roles.policy.can_view)(persona, entity):
            target = "/"
        response = RedirectResponse(f"{prefix_of(request)}{target}", status_code=303)
        response.set_cookie(
            COOKIE_NAME, roles.sign(persona.id), path=prefix_of(request) or "/", httponly=True, samesite="lax",
            secure=request.headers.get("x-forwarded-proto") == "https",
        )
        return response

    return roles
