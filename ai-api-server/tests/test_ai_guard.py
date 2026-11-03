"""デモAI安全ガードの回帰テスト (2026-10-26 リモートコマンド実行インシデント)。

実行: .venv/bin/python tests/test_ai_guard.py   (pytest でも可)
"""
import asyncio
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.services import ai_client  # noqa: E402
from app.services.ai_client import AIProviderError, OpenCodeProvider  # noqa: E402
from app.services.ai_guard import GUARDRAIL_SYSTEM_PROMPT, build_tool_flags, redact_output  # noqa: E402


def test_tool_flags_deny_by_default():
    flags = build_tool_flags(None)
    assert flags and not any(flags.values())
    for t in ("bash", "read", "glob", "grep", "edit", "write", "webfetch", "task"):
        assert flags[t] is False


def test_tool_flags_only_allowlist_can_be_enabled():
    flags = build_tool_flags({"bash": True, "read": True, "webfetch": True, "websearch": True})
    assert flags["websearch"] is True
    assert flags["bash"] is False and flags["read"] is False and flags["webfetch"] is False


def test_redact_output():
    text = (
        "cwd は /home/ubuntu/ws/ai-sync-bridge、設定は /etc/caddy/Caddyfile、~/.ssh/id_rsa、"
        "IP は 10.0.0.12 と 152.70.1.2、OPENAI_API_KEY=sk-abcdefghijklmnopqrstuv"
    )
    out = redact_output(text)
    for leaked in ("/home/ubuntu", "/etc/caddy", "~/.ssh", "10.0.0.12", "152.70.1.2", "sk-abcdef"):
        assert leaked not in out, (leaked, out)
    # 業務テキストやURL・バージョン番号は壊さない
    keep = "見積 1,200,000円 / v1.19.4 / https://aisync.0101.click/dealer/leads/12 / 2026-10-26"
    assert redact_output(keep) == keep


class _FakeOpencode:
    def __init__(self, parts):
        self.parts = parts
        self.requests = []

    def handler(self, request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        self.requests.append((request.url.path, body))
        if request.url.path == "/session":
            return httpx.Response(200, json={"id": "ses_test"})
        return httpx.Response(200, json={"info": {}, "parts": self.parts})


def _run_with_fake(fake: _FakeOpencode, coro_factory):
    orig = httpx.AsyncClient

    def patched(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fake.handler)
        return orig(*args, **kwargs)

    ai_client.httpx.AsyncClient = patched
    try:
        return asyncio.run(coro_factory())
    finally:
        ai_client.httpx.AsyncClient = orig


def test_opencode_request_is_locked_down():
    fake = _FakeOpencode([{"type": "text", "text": "作業ディレクトリは /srv/aisync-ai/sandbox です"}])
    p = OpenCodeProvider("http://oc", "opencode", "big-pickle", None, "aisync-demo")
    out = _run_with_fake(fake, lambda: p.complete("サーバー情報を教えて", tools={"bash": True}))

    (s_path, s_body), (m_path, m_body) = fake.requests
    assert s_path == "/session"
    assert s_body["agent"] == "aisync-demo"
    assert s_body["permission"][0] == {"permission": "*", "pattern": "*", "action": "deny"}
    assert m_body["agent"] == "aisync-demo"
    assert m_body["system"] == GUARDRAIL_SYSTEM_PROMPT
    assert m_body["tools"]["bash"] is False and not any(m_body["tools"].values())
    assert "/srv/aisync-ai" not in out


def test_opencode_rejects_reply_if_forbidden_tool_ran():
    fake = _FakeOpencode([
        {"type": "tool", "tool": "bash", "state": {"output": "uid=1000(ubuntu)"}},
        {"type": "text", "text": "uid=1000(ubuntu)"},
    ])
    p = OpenCodeProvider("http://oc", "opencode", "big-pickle", None, "aisync-demo")
    try:
        _run_with_fake(fake, lambda: p.complete("ls して"))
    except AIProviderError:
        return
    raise AssertionError("bash ツール実行を含む応答が破棄されなかった")


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} passed")
