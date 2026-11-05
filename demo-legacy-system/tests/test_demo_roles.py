"""ロール入口と画面権限のテスト。ネットワーク不要。一時 DB を使い、本番の erp.db には触れない。

実行: demo-legacy-system/.venv/bin/python demo-legacy-system/tests/test_demo_roles.py   (pytest でも可)
"""
import os
import re
import sys
import tempfile
from pathlib import Path
from urllib.parse import parse_qs, urlsplit

ROOT = Path(__file__).resolve().parents[1]
os.environ["AISB_ERP_DB_PATH"] = str(Path(tempfile.mkdtemp()) / "erp-test.db")
os.environ["AISB_EMBED_ENABLED"] = "1"
sys.path[:0] = [str(ROOT), str(ROOT.parent / "ai-api-server")]

from fastapi.testclient import TestClient  # noqa: E402
from starlette.routing import Route  # noqa: E402

import data as db  # noqa: E402
import demo_roles  # noqa: E402
import main  # noqa: E402

PUBLIC = {"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Proto": "https", "X-Forwarded-Prefix": "/erp"}
SELECTABLE = ("admin", "sales", "manager", "hr")

# 期待する権限表。bridge.yaml を変えるときは、この表も意図して変える
EXPECTED_VIEW = {
    "admin": set(demo_roles._ENTITIES),
    "sales": {"Customer", "Order", "Estimate", "Product", "Property"},
    "manager": {"Customer", "Order", "Estimate", "Invoice", "PurchaseOrder", "Supplier", "Employee", "Product",
                "InventoryTransaction", "GoodsReceipt", "ArAp", "Profit"},
    "hr": {"Employee", "Product"},
}
LIST_PATH = {path.split("/")[1]: path for path, _, _ in demo_roles.NAV_ITEMS}


def _client(addr=("203.0.113.9", 50000)):
    async def with_addr(scope, receive, send):
        if scope["type"] == "http":
            scope["client"] = addr
        await main.app(scope, receive, send)

    return TestClient(with_addr, follow_redirects=False, base_url="https://testserver")


def _as(persona):
    c = _client()
    res = c.post("/role", data={"persona": persona, "next": "/"}, headers=PUBLIC)
    assert res.status_code == 303, res.status_code
    # Cookie は /erp に限定され Secure なので、テストでは値だけを取り出して直接送る
    value = re.search(rf"{demo_roles.COOKIE_NAME}=([^;]+)", res.headers["set-cookie"]).group(1).strip('"')
    c.headers.update({**PUBLIC, "Cookie": f"{demo_roles.COOKIE_NAME}={value}"})
    return c


def test_anonymous_public_is_sent_to_role_select():
    c = _client()
    res = c.get("/Employee/List?page=2", headers=PUBLIC)
    assert res.status_code == 303
    loc = urlsplit(res.headers["location"])
    assert loc.path == "/erp/role" and parse_qs(loc.query)["next"] == ["/Employee/List?page=2"]
    assert c.get("/", headers=PUBLIC).status_code == 303
    assert c.get("/api/Customer/list", headers=PUBLIC).status_code == 401
    assert c.get("/api/entities", headers=PUBLIC).status_code == 401
    # 入口そのものと静的ファイルは見られる。入口に AI パネルは出さない
    page = c.get("/role", headers=PUBLIC)
    assert page.status_code == 200 and "aisb-embed/static" not in page.text
    assert c.get("/static/css/site.css", headers=PUBLIC).status_code == 200
    assert c.get("/aisb-embed/status", headers=PUBLIC).status_code == 200


def test_role_select_lists_only_selectable_personas():
    page = _client().get("/role", headers=PUBLIC).text
    assert re.findall(r'name="persona" value="(\w+)"', page) == list(SELECTABLE)
    assert "別テナント" not in page


def test_internal_calls_are_not_restricted():
    local = _client(("127.0.0.1", 50000))
    assert local.get("/").status_code == 200
    res = local.get("/api/Employee/list", params={"limit": 1000})
    assert res.status_code == 200 and res.json()["count"] == len(db.employees)
    # 同じマシンでもプロキシ経由なら公開経路として扱う
    assert local.get("/", headers={"X-Forwarded-For": "127.0.0.1"}).status_code == 303
    # 外部からの直接アクセスも内部扱いにしない
    assert _client().get("/").status_code == 303


def test_cookie_attributes():
    res = _client().post("/role", data={"persona": "sales", "next": "/Order/List"}, headers=PUBLIC)
    assert res.status_code == 303 and res.headers["location"] == "/erp/Order/List"
    cookie = res.headers["set-cookie"].lower()
    assert all(x in cookie for x in ("httponly", "samesite=lax", "path=/erp", "secure"))
    assert "max-age" not in cookie and "expires" not in cookie  # ブラウザを閉じると消える


def test_invalid_persona_and_tampered_cookie_are_rejected():
    c = _client()
    for persona in ("other", "nobody", ""):
        res = c.post("/role", data={"persona": persona}, headers=PUBLIC)
        assert "set-cookie" not in res.headers, persona
    signed_sales = _as("sales").headers["Cookie"].split("=", 1)[1]
    sig = signed_sales.split(".", 1)[1]
    for value in (f"admin.{sig}", "admin", "admin.", f"sales.{'0' * 64}", f"other.{sig}"):
        headers = {**PUBLIC, "Cookie": f"{demo_roles.COOKIE_NAME}={value}"}
        assert _client().get("/Employee/List", headers=headers).status_code == 303, value


def test_screen_and_api_matrix():
    for persona, allowed in EXPECTED_VIEW.items():
        c = _as(persona)
        for entity in demo_roles._ENTITIES:
            want = entity in allowed
            screen = c.get(LIST_PATH[entity]).status_code
            assert screen == (200 if want else 403), (persona, entity, screen)
            api = c.get(f"/api/{entity}/list").status_code
            assert api == (200 if want else 403), (persona, entity, api)
        listed = {e["entity"] for e in c.get("/api/entities").json()}
        assert listed == allowed, persona
    assert _as("hr").get("/Stock/Inquiry").status_code == 200
    assert _as("sales").get("/Customer/Search").status_code == 200
    assert _as("hr").post("/Customer/Search", data={"keyword": "x"}).status_code == 403


def test_nav_and_home_follow_role():
    hr = _as("hr").get("/").text
    assert "従業員管理" in hr and "顧客管理" not in hr and "受注合計金額" not in hr and "顧客数" not in hr
    assert '"id": "hr"' in hr and '"panels": ["bridge"]' in hr
    sales = _as("sales").get("/").text
    assert "顧客管理" in sales and "受注合計金額" in sales and "従業員管理" not in sales and "請求管理" not in sales
    admin = _as("admin").get("/").text
    assert '"panels": ["*"]' in admin
    # 権限エラーの画面にも AI パネルと切り替え導線を出す
    denied = _as("sales").get("/Employee/List")
    assert denied.status_code == 403 and "aisb-embed/static" in denied.text and "/erp/role" in denied.text


def test_employee_rows_follow_department():
    rows = list(db.employees.values())
    keiri = [e for e in rows if e["Department"] == "経理部"]
    other = next(e for e in rows if e["Department"] != "経理部")
    assert keiri

    mgr = _as("manager")
    api = mgr.get("/api/Employee/list", params={"limit": 1000}).json()
    assert api["count"] == len(keiri) and {r["Department"] for r in api["rows"]} == {"経理部"}
    assert other["Name"] not in mgr.get("/api/Employee/list", params={"q": other["Name"]}).text
    assert mgr.get(f"/Employee/Detail/{keiri[0]['Id']}").status_code == 200
    assert mgr.get(f"/Employee/Detail/{other['Id']}").status_code == 303
    assert mgr.get(f"/api/Employee/detail/{other['Id']}").status_code == 404
    assert mgr.get(f"/api/Employee/detail/{keiri[0]['Id']}").status_code == 200
    assert f"全{len(keiri)}件" in mgr.get("/Employee/List").text

    hr = _as("hr")
    assert hr.get("/api/Employee/list", params={"limit": 1000}).json()["count"] == len(rows)
    assert hr.get(f"/api/Employee/detail/{other['Id']}").status_code == 200


def test_employee_write_is_hr_only():
    target = next(iter(db.employees.values()))
    before = dict(target)
    mgr = _as("manager")
    assert mgr.get("/Employee/Entry").status_code == 403
    assert mgr.post("/Employee/Entry", data={"Name": "x"}).status_code == 403
    assert mgr.post(f"/Employee/Entry/{target['Id']}", data={"Name": "x"}).status_code == 403
    assert db.employees[target["Id"]] == before
    listing = mgr.get("/Employee/List").text
    assert "/Employee/Entry" not in listing and "/Employee/Detail/" in listing

    hr = _as("hr")
    assert hr.get("/Employee/Entry").status_code == 200
    assert "/Employee/Entry" in hr.get("/Employee/List").text


def test_safe_next_blocks_external_targets():
    for bad in ("https://evil.example/", "//evil.example/", "/\\evil.example", "evil", "", None, "/x\r\nSet-Cookie: a=b", "/role"):
        assert demo_roles.safe_next(bad) == "/", bad
    assert demo_roles.safe_next("/Order/List?page=2") == "/Order/List?page=2"
    res = _client().post("/role", data={"persona": "sales", "next": "https://evil.example/"}, headers=PUBLIC)
    assert res.headers["location"] == "/erp/"


def test_next_outside_the_role_falls_back_to_home():
    def landed(persona, target):
        res = _client().post("/role", data={"persona": persona, "next": target}, headers=PUBLIC)
        return res.headers["location"]

    assert landed("hr", "/Customer/List") == "/erp/"
    assert landed("hr", "/Employee/List?page=2") == "/erp/Employee/List?page=2"
    assert landed("manager", "/Employee/Entry") == "/erp/"
    assert landed("hr", "/ai-panel") == "/erp/ai-panel"


def test_every_route_is_classified():
    """業務画面を追加したのに権限を定義し忘れる、を防ぐ。"""
    role_only = {"/", "/ai-panel", "/role", "/api/entities", "/api/{entity}/list", "/api/{entity}/detail/{rid}",
                 "/aisb-embed/status", "/aisb-embed/toggle", "/aisb-embed/admin",
                 "/openapi.json", "/docs", "/docs/oauth2-redirect", "/redoc"}
    policy = main.roles.policy
    for route in main.app.routes:
        if not isinstance(route, Route) or route.path in role_only:
            continue
        entity, _ = demo_roles.classify(route.path)
        assert entity is not None and entity in policy.acls, route.path


def test_policy_matches_bridge_acl():
    """画面の権限と、AI パネルの検索結果を絞る権限が食い違わないこと。"""
    import yaml
    from app.bridge.acl import Principal, can_read
    from app.bridge.models import EntitySpec

    profile = yaml.safe_load((ROOT / "aisb_profile" / "bridge.yaml").read_text(encoding="utf-8"))
    policy = main.roles.policy
    rows = [{"Department": d, "Dept": d} for d in ("経理部", "営業部", "製造部", "")]
    checked = 0
    for source in profile["sources"]:
        for ent in source["entities"]:
            spec = EntitySpec(name=ent["name"], pk=ent["pk"], text_fields=tuple(ent["text"]), acl=ent["acl"])
            for raw in profile["demo"]["personas"]:
                principal = Principal(user_id=raw["user_id"], tenant=raw["tenant"], roles=tuple(raw["roles"]),
                                      depts=tuple(raw.get("depts") or ()))
                persona = policy.personas[raw["id"]]
                for row in rows:
                    assert policy.row_visible(persona, ent["name"], row) == can_read(principal, spec.acl_of(row)), (raw["id"], ent["name"], row)
                    checked += 1
    assert checked > 100


def test_every_screen_has_a_policy():
    for _, _, entity in demo_roles.NAV_ITEMS:
        assert entity in main.roles.policy.acls, entity


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_") and callable(f)]
    for name, fn in tests:
        fn()
        print(f"ok {name}")
    print(f"{len(tests)} passed")
