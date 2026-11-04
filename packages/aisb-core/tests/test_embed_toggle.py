"""/aisb-embed/toggle の認可テスト。ネットワーク不要。

実行: <demo>/.venv/bin/python packages/aisb-core/tests/test_embed_toggle.py   (pytest でも可)
"""
import os
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from aisb_embed import config, routes

LOCAL = ("127.0.0.1", 50000)
REMOTE = ("203.0.113.9", 50000)
KEY_ENV = "AISB_EMBED_ADMIN_KEY"


def _client(client_addr):
    app = FastAPI()
    app.include_router(routes.router)

    async def with_client_addr(scope, receive, send):
        if scope["type"] == "http":
            scope["client"] = client_addr
        await app(scope, receive, send)

    return TestClient(with_client_addr)


def _setup(key=None):
    config.set_state_file(Path(tempfile.mkdtemp()) / "state.json")
    os.environ.pop(config._ENV_VAR, None)
    os.environ.pop(KEY_ENV, None)
    if key is not None:
        os.environ[KEY_ENV] = key
    assert config.is_enabled() is True


def _denied(client, headers=None):
    res = client.post("/aisb-embed/toggle", json={"enabled": False}, headers=headers or {})
    assert res.status_code == 403, res.status_code
    assert config.is_enabled() is True, "拒否されたのに状態が変わった"


def test_local_direct_can_toggle():
    _setup()
    res = _client(LOCAL).post("/aisb-embed/toggle", json={"enabled": False})
    assert res.status_code == 200 and res.json()["enabled"] is False
    assert config.is_enabled() is False


def test_remote_is_denied():
    _setup()
    _denied(_client(REMOTE))


def test_proxied_request_from_loopback_is_denied():
    # Caddy 経由は接続元が 127.0.0.1 になる。詐称した値でも転送ヘッダがあれば公開経路として扱う
    _setup()
    client = _client(LOCAL)
    for name in routes._PROXY_HEADERS:
        _denied(client, {name: "127.0.0.1"})


def test_key_is_required_and_compared():
    _setup(key="right-key")
    client = _client(REMOTE)
    _denied(client)
    _denied(client, {"X-AISB-Admin-Key": "wrong-key"})
    res = client.post("/aisb-embed/toggle", json={"enabled": False}, headers={"X-AISB-Admin-Key": "right-key"})
    assert res.status_code == 200
    assert config.is_enabled() is False


def test_unset_or_empty_key_never_matches():
    for key in (None, ""):
        _setup(key=key)
        _denied(_client(REMOTE), {"X-AISB-Admin-Key": ""})


def test_admin_page_hides_control_on_public_path():
    _setup()
    public = _client(LOCAL).get("/aisb-embed/admin", headers={"X-Forwarded-For": "203.0.113.9", "X-Forwarded-Prefix": "/erp"})
    assert public.status_code == 200 and "toggle-btn" not in public.text and "/aisb-embed/toggle" not in public.text
    assert "toggle-btn" in _client(LOCAL).get("/aisb-embed/admin").text


if __name__ == "__main__":
    tests = [(n, f) for n, f in sorted(globals().items()) if n.startswith("test_")]
    for name, fn in tests:
        fn()
        print("ok", name)
    print(f"{len(tests)} passed")
