"""/api/admin, /api/search の認可テスト。ネットワーク不要。

実行: .venv/bin/python tests/test_operator_auth.py   (pytest でも可)
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from app.deps import get_admin_service, get_ai_provider, get_search_service  # noqa: E402
from app.main import app  # noqa: E402
from app.services.ai_client import MockProvider  # noqa: E402

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("203.0.113.9", 50000)
KEY_ENV = "AISB_API_ADMIN_KEY"
PROXIED = {"x-forwarded-for": "203.0.113.9"}
STATS = {
    "demo_mode": True, "ai_provider": "mock", "vector_backend": "brute-force", "customer_count": 0,
    "order_count": 0, "workflow_count": 0, "workflow_execution_count": 0, "unread_notification_count": 0,
    "generated_at": "2026-01-01T00:00:00",
}
ENDPOINTS = [
    ("GET", "/api/admin/stats", None),
    ("GET", "/api/admin/stats/insight", None),
    ("GET", "/api/admin/audit-log", None),
    ("POST", "/api/admin/reset-demo-data", None),
    ("POST", "/api/search", {"query": "x", "top_k": 1}),
]


class _FakeAdmin:
    def __init__(self):
        self.resets = 0
        self.audit_log = type("L", (), {"list": staticmethod(lambda limit: [])})

    def stats(self):
        return STATS

    def reset_demo_data(self):
        self.resets += 1
        return STATS


class _FakeSearch:
    async def search(self, query, top_k):
        return {"query": query, "backend": "fake", "results": []}


def _client(client_addr, admin):
    app.dependency_overrides[get_admin_service] = lambda: admin
    app.dependency_overrides[get_search_service] = lambda: _FakeSearch()
    app.dependency_overrides[get_ai_provider] = MockProvider

    async def with_client_addr(scope, receive, send):
        if scope["type"] == "http":
            scope["client"] = client_addr
        await app(scope, receive, send)

    return TestClient(with_client_addr)


def _codes(client, headers=None):
    return {
        path: client.request(method, path, json=body, headers=headers or {}).status_code
        for method, path, body in ENDPOINTS
    }


def _with_key(key):
    saved = os.environ.pop(KEY_ENV, None)
    if key is not None:
        os.environ[KEY_ENV] = key
    return saved


def _restore(saved):
    os.environ.pop(KEY_ENV, None)
    if saved is not None:
        os.environ[KEY_ENV] = saved
    app.dependency_overrides.clear()


def test_public_route_is_denied_without_key():
    saved = _with_key(None)
    try:
        admin = _FakeAdmin()
        for addr, headers in ((REMOTE, {}), (LOCAL, PROXIED), (LOCAL, {"forwarded": "for=127.0.0.1"})):
            codes = _codes(_client(addr, admin), headers)
            assert set(codes.values()) == {403}, (addr, headers, codes)
        assert admin.resets == 0, "拒否されたのにリセットが実行された"
    finally:
        _restore(saved)


def test_spoofing_loopback_or_empty_key_is_denied():
    saved = _with_key(None)
    try:
        admin = _FakeAdmin()
        spoofed = {"x-forwarded-for": "127.0.0.1", "x-aisb-admin-key": ""}
        assert set(_codes(_client(LOCAL, admin), spoofed).values()) == {403}
        # キー未設定のとき、空のキーを送っても一致扱いにしない
        assert set(_codes(_client(REMOTE, admin), {"x-aisb-admin-key": ""}).values()) == {403}
    finally:
        _restore(saved)


def test_wrong_key_is_denied():
    saved = _with_key("correct-key")
    try:
        admin = _FakeAdmin()
        assert set(_codes(_client(REMOTE, admin), {"x-aisb-admin-key": "wrong"}).values()) == {403}
        # 非 ASCII のキーでも 500 にせず拒否する
        res = _client(REMOTE, admin).get("/api/admin/stats", headers={"x-aisb-admin-key": b"\xe3\x81\x82"})
        assert res.status_code == 403, res.status_code
    finally:
        _restore(saved)


def test_correct_key_is_allowed_on_public_route():
    saved = _with_key("correct-key")
    try:
        admin = _FakeAdmin()
        headers = {**PROXIED, "x-aisb-admin-key": "correct-key"}
        codes = _codes(_client(LOCAL, admin), headers)
        assert set(codes.values()) == {200}, codes
        assert admin.resets == 1
    finally:
        _restore(saved)


def test_local_direct_is_allowed_without_key():
    saved = _with_key(None)
    try:
        codes = _codes(_client(LOCAL, _FakeAdmin()))
        assert set(codes.values()) == {200}, codes
    finally:
        _restore(saved)


def test_every_admin_and_search_route_is_covered():
    """/api/admin に後から追加したルートが認可から漏れないことを確認する。"""
    from app.operator_auth import require_operator

    checked = 0
    for route in app.routes:
        path = getattr(route, "path", "")
        if path.startswith(("/api/admin", "/api/search")):
            deps = [d.call for d in route.dependant.dependencies]
            assert require_operator in deps, path
            checked += 1
    assert checked == len(ENDPOINTS), checked


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
            print("PASS", name)
