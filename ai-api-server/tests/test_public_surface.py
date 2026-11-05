"""公開経路から匿名で届く範囲の回帰テスト。ネットワーク不要。

実行: .venv/bin/python tests/test_public_surface.py   (pytest でも可)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ["AISB_DB_PATH"] = os.path.join(tempfile.mkdtemp(prefix="aisb-surface-"), "t.db")
os.environ["AISB_DEMO_MODE"] = "true"

from fastapi.routing import APIRoute  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.deps import (  # noqa: E402
    get_admin_service, get_ai_provider, get_chat_service, get_notification_center, get_workflow_engine,
)
from app.main import app  # noqa: E402
from app.operator_auth import require_operator  # noqa: E402
from app.services.chat_service import ChatService  # noqa: E402
from app.services.demo_data import MAX_CHAT_SESSIONS, MAX_HISTORY_MESSAGES, get_demo_store  # noqa: E402
from app.services.notification_service import MAX_NOTIFICATIONS, NotificationCenter  # noqa: E402
from app.services.rate_limit import current_client  # noqa: E402
from app.services.request_limits import DEFAULT_MAX_BODY, OCR_MAX_BODY  # noqa: E402

VISITOR_A = ("203.0.113.9", 50000)
VISITOR_B = ("203.0.113.10", 50000)
LOCAL = ("127.0.0.1", 50000)
PROXIED = {"x-forwarded-for": "203.0.113.9"}
WRITE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}

# 公開デモの画面が使う、または副作用がなく匿名でよい書き込み系。追加するときは理由を確認すること。
ANONYMOUS_WRITES = {
    ("POST", "/api/chat"),
    ("POST", "/api/ocr"), ("POST", "/api/ocr/register"),
    ("POST", "/api/nlsql/query"),
    ("POST", "/api/local-ai/assist"),
    ("POST", "/api/conversational-input"), ("POST", "/api/conversational-input/register"),
    ("POST", "/api/cross-analysis/generate"),
    ("POST", "/api/company/search"), ("POST", "/api/company/register"),
    ("POST", "/api/property/search"), ("POST", "/api/property/register"),
    ("POST", "/api/recommend"),
    ("POST", "/api/profit-report/report"), ("POST", "/api/ar-ap/aging"),
    ("POST", "/api/realestate/valuation"), ("POST", "/api/realestate/commission-check"),
    ("POST", "/api/purchase-order"), ("POST", "/api/purchase-order/goods-receipt"),
    ("POST", "/api/push/check"), ("POST", "/api/push/subscribe"), ("POST", "/api/push/unsubscribe"),
    ("POST", "/api/notifications/{notification_id}/read"), ("POST", "/api/notifications/read-all"),
    ("POST", "/api/workflows/{workflow_id}/execute"), ("PATCH", "/api/workflows/{workflow_id}/toggle"),
    ("POST", "/api/workflows/evaluate-triggers"),
    # 以下はブリッジ自身の主体判定と回数制限で守る(app/bridge/acl.py, app/bridge/demo.py)
    ("POST", "/api/bridge/search"), ("POST", "/api/bridge/ask"), ("DELETE", "/api/bridge/ask/{session_id}"),
    ("POST", "/api/bridge/sync"),
    ("POST", "/api/bridge/demo/search"), ("POST", "/api/bridge/demo/ask"), ("POST", "/api/bridge/demo/sync"),
}
OPERATOR_READS = {"/api/analysis-history", "/api/push/subscriptions"}
OPERATOR_WRITES = [
    ("POST", "/api/customers", {"name": "x"}), ("PUT", "/api/customers/1", {"name": "x"}),
    ("DELETE", "/api/customers/1", None),
    ("POST", "/api/inventory", {"name": "x", "sku": "x", "stock": 1, "reorder_point": 1, "unit_cost": 1}),
    ("PUT", "/api/inventory/1", {"stock": 1}),
    ("POST", "/api/orders", {"customer_id": 1, "product": "x", "qty": 1, "amount": 1}),
    ("POST", "/api/notifications", {"title": "<img src=x onerror=alert(1)>", "message": "x"}),
    ("POST", "/api/workflows", {"name": "x", "steps": []}), ("PUT", "/api/workflows/wf_demo_stock_alert", {"name": "x"}),
    ("DELETE", "/api/workflows/wf_demo_stock_alert", None),
    ("POST", "/api/analysis-history", {"type": "x", "query": "x", "result": "x"}),
]


class _RecordingAi:
    name = "mock"

    def __init__(self):
        self.calls = []

    async def complete(self, prompt, history=None, tools=None):
        self.calls.append((prompt, list(history or [])))
        return f"reply{len(self.calls)}"


def _client(peer=VISITOR_A):
    async def with_peer(scope, receive, send):
        if scope["type"] == "http":
            scope["client"] = peer
        await app(scope, receive, send)

    return TestClient(with_peer, raise_server_exceptions=False)


def _chat_with(ai):
    app.dependency_overrides[get_ai_provider] = lambda: ai
    app.dependency_overrides[get_chat_service] = lambda: ChatService(ai, get_demo_store())


def test_every_write_route_is_classified():
    """分類していない書き込みルートを足すとここで落ちる。"""
    unclassified = []
    seen = set()
    for route in app.routes:
        if not isinstance(route, APIRoute):
            continue
        guarded = require_operator in [d.call for d in route.dependant.dependencies]
        for method in route.methods & WRITE_METHODS:
            seen.add((method, route.path))
            if not guarded and (method, route.path) not in ANONYMOUS_WRITES:
                unclassified.append((method, route.path))
    assert not unclassified, unclassified
    assert not ANONYMOUS_WRITES - seen, ANONYMOUS_WRITES - seen


def test_operator_routes_reject_public_and_allow_local():
    client = _client()
    for method, path, body in OPERATOR_WRITES:
        assert client.request(method, path, json=body).status_code == 403, (method, path)
    for path in OPERATOR_READS:
        assert client.get(path).status_code == 403, path
    # 同じマシンの Caddy 経由(接続元 127.0.0.1 + X-Forwarded-For)も公開扱い
    assert _client(LOCAL).post("/api/notifications", json={"title": "t", "message": "m"}, headers=PROXIED).status_code == 403
    assert _client(LOCAL).post("/api/notifications", json={"title": "t", "message": "m"}).status_code == 201
    get_notification_center().reset()


def test_chat_history_is_isolated_between_visitors():
    ai = _RecordingAi()
    _chat_with(ai)
    try:
        body = {"session_id": "sidebar", "message": "secret-of-a"}
        assert _client(VISITOR_A).post("/api/chat", json=body).status_code == 200
        assert _client(VISITOR_A).post("/api/chat", json={"session_id": "sidebar", "message": "second"}).status_code == 200
        assert _client(VISITOR_B).post("/api/chat", json={"session_id": "sidebar", "message": "hello"}).status_code == 200
        a2_history = ai.calls[1][1]
        b_history = ai.calls[2][1]
        assert [h["content"] for h in a2_history] == ["secret-of-a", "reply1"], a2_history
        assert b_history == [], b_history
        # 今回の発言が履歴にも入って二重にならない
        assert ai.calls[0][1] == []
    finally:
        app.dependency_overrides.clear()


def test_chat_history_is_bounded():
    store = get_demo_store()
    store.chat_histories.clear()
    token = current_client.set("198.51.100.1")
    try:
        for i in range(MAX_HISTORY_MESSAGES + 10):
            store.append_history("one", "user", str(i))
        assert len(store.get_history("one")) == MAX_HISTORY_MESSAGES
        for i in range(MAX_CHAT_SESSIONS + 10):
            store.get_history(f"s{i}")
        assert len(store.chat_histories) == MAX_CHAT_SESSIONS
    finally:
        current_client.reset(token)
        store.chat_histories.clear()


def test_field_limits():
    client = _client()
    cases = [
        ("/api/chat", {"message": "x" * 8001}),
        ("/api/chat", {"message": "x", "session_id": "s" * 101}),
        ("/api/chat", {"message": ""}),
        ("/api/local-ai/assist", {"message": "x" * 8001}),
        ("/api/local-ai/assist", {"message": "x", "screen_context": {"a": "x" * 16001}}),
        ("/api/nlsql/query", {"entity": "Customer", "question": "x" * 2001}),
        ("/api/company/search", {"keyword": "x" * 501}),
        ("/api/push/subscribe", {"endpoint": "x" * 2049}),
        ("/api/workflows/wf_demo_stock_alert/execute", {"context": {"a": "x" * 16001}}),
    ]
    for path, body in cases:
        assert client.post(path, json=body).status_code == 422, (path, list(body))


def test_body_limit_by_content_length_and_stream():
    client = _client()
    big = b"x" * (DEFAULT_MAX_BODY + 1)
    headers = {"content-type": "application/json"}
    assert client.post("/api/chat", content=big, headers=headers).status_code == 413

    def chunks():
        for _ in range(4):
            yield b"x" * (DEFAULT_MAX_BODY // 2)

    # Content-Length なし(chunked)でも本文を読む途中で止まる
    assert client.post("/api/chat", content=chunks(), headers=headers).status_code == 413


def test_ocr_body_limit_is_larger_but_bounded():
    client = _client()
    # 既定の上限を超えても OCR の上限内なら本文を受け付ける(doc_type 不正→ファイル欠落の 422)
    res = client.post("/api/ocr", content=b"x" * (DEFAULT_MAX_BODY + 1),
                      headers={"content-type": "multipart/form-data; boundary=b"})
    assert res.status_code != 413, res.status_code
    res = client.post("/api/ocr", content=b"x" * (OCR_MAX_BODY + 1),
                      headers={"content-type": "multipart/form-data; boundary=b"})
    assert res.status_code == 413, res.status_code


def test_cors_allowlist():
    client = _client()

    def preflight(origin):
        return client.options("/api/chat", headers={
            "origin": origin, "access-control-request-method": "POST", "access-control-request-headers": "content-type",
        })

    for origin in ("https://aisync.0101.click", "http://localhost:5010", "chrome-extension://" + "a" * 32):
        res = preflight(origin)
        assert res.status_code == 200, origin
        assert res.headers["access-control-allow-origin"] == origin
        assert "access-control-allow-credentials" not in res.headers
    for origin in ("https://evil.example", "https://aisync.0101.click.evil.example", "chrome-extension://short", "null"):
        res = preflight(origin)
        assert "access-control-allow-origin" not in res.headers, origin
        get = client.get("/api/health", headers={"origin": origin})
        assert "access-control-allow-origin" not in get.headers, origin


def test_reset_restores_workflows_and_clears_notifications():
    engine = get_workflow_engine()
    center = get_notification_center()
    admin = get_admin_service()
    seeded = {w["id"]: w["enabled"] for w in engine.list_workflows()}
    assert seeded
    # 匿名で切り替えられる有効/無効と、運用者が足した定義・通知
    first = next(iter(seeded))
    assert _client().patch(f"/api/workflows/{first}/toggle").status_code == 200
    assert engine.get_workflow(first)["enabled"] != seeded[first]
    engine.add_workflow({"name": "added", "steps": []})
    center.push(title="t", message="m")

    for _ in range(2):
        stats = admin.reset_demo_data()
        assert {w["id"]: w["enabled"] for w in engine.list_workflows()} == seeded
        assert center.list() == []
        assert stats["unread_notification_count"] == 0
        assert engine.execution_history == []


def test_in_memory_logs_are_bounded():
    center = NotificationCenter()
    for _ in range(MAX_NOTIFICATIONS + 5):
        center.push(title="t", message="m")
    assert len(center.notifications) == MAX_NOTIFICATIONS


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
