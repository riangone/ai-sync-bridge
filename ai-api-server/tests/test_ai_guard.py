"""デモAI安全ガードの回帰テスト (2026-10-26 リモートコマンド実行インシデント)。

実行: .venv/bin/python tests/test_ai_guard.py   (pytest でも可)
"""
import asyncio
import json
import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import httpx  # noqa: E402

from app.services import ai_client  # noqa: E402
from app.services.ai_client import AIProviderError, AntigravityProvider, OpenCodeProvider  # noqa: E402
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


# --- antigravity: 実 CLI の代わりに、渡された引数等を記録して指定のイベントを返す偽 CLI を使う ---

def _tool_event(tool):
    return {"event": "step_update", "step_update": {"step_type": "tool", "tool_name": tool, "state": "ACTIVE"}}


def _result_event(response="回答", status="SUCCESS", **extra):
    return {"event": "result", "result": {"status": status, "response": response, **extra}}


def _fake_antigravity(tmp, events, exit_code=0, stderr="", sleep=0):
    record = os.path.join(tmp, "record.json")
    script = os.path.join(tmp, "fake-antigravity")
    with open(script, "w", encoding="utf-8") as f:
        f.write(f"""#!{sys.executable}
import json, os, sys, time
with open({record!r}, "w") as out:
    json.dump({{"argv": sys.argv[1:], "env": dict(os.environ), "cwd": os.getcwd(), "stdin": sys.stdin.read()}}, out)
for event in {events!r}:
    print(json.dumps(event), flush=True)
sys.stderr.write({stderr!r})
time.sleep({sleep!r})
sys.exit({exit_code!r})
""")
    os.chmod(script, 0o700)
    return script, record


def _antigravity(tmp, script, **kwargs):
    return AntigravityProvider(script, "gemini-3.8-flash-low", os.path.join(tmp, "work"), **kwargs)


def _assert_provider_error(coro, expected):
    try:
        asyncio.run(coro)
    except AIProviderError as exc:
        assert expected in str(exc), str(exc)
        return
    raise AssertionError(f"AIProviderError が発生しなかった: {expected}")


def test_antigravity_invocation_is_locked_down():
    with tempfile.TemporaryDirectory() as tmp:
        script, record = _fake_antigravity(tmp, [_result_event("場所は /home/ubuntu/ws です")])
        p = _antigravity(tmp, script)
        os.environ["AISYNC_TEST_SECRET"] = "must-not-leak"
        try:
            out = asyncio.run(p.complete("質問", history=[{"role": "user", "content": "前の質問"}], tools={"bash": True}))
        finally:
            del os.environ["AISYNC_TEST_SECRET"]
        with open(record) as f:
            rec = json.load(f)
        argv = rec["argv"]
        assert argv[argv.index("--agent") + 1] == "aisync-demo"
        assert argv[argv.index("--model") + 1] == "gemini-3.8-flash-low"
        assert "--dangerously-skip-permissions" not in argv
        assert "--disable-slash-commands" in argv and "--sandbox" in argv
        settings = json.loads(argv[argv.index("--settings") + 1])
        assert settings["permissions"]["allow"] == [] and settings["allowNonWorkspaceAccess"] is False
        # プロンプトは引数(ps から見える)ではなく stdin で渡す
        assert not any("質問" in a for a in argv)
        content = json.loads(rec["stdin"])["message"]["content"]
        assert "前の質問" in content and "質問" in content
        assert "AISYNC_TEST_SECRET" not in rec["env"]
        assert rec["cwd"] == os.path.realpath(os.path.join(tmp, "work"))
        assert "/home/ubuntu" not in out


def test_antigravity_agents_expose_only_allowed_tools():
    with tempfile.TemporaryDirectory() as tmp:
        script, _ = _fake_antigravity(tmp, [_result_event()])
        p = _antigravity(tmp, script)
        agents = os.path.join(p.workdir, ".agents", "agents")
        with open(os.path.join(agents, "aisync-demo.md"), encoding="utf-8") as f:
            base = f.read()
        with open(os.path.join(agents, "aisync-demo-web.md"), encoding="utf-8") as f:
            web = f.read()
        assert "excludeDefaultComponents: true" in base and "tools: []" in base
        assert "tools: [search_web]" in web
        assert GUARDRAIL_SYSTEM_PROMPT in base and GUARDRAIL_SYSTEM_PROMPT in web


def test_antigravity_web_agent_only_on_explicit_request():
    with tempfile.TemporaryDirectory() as tmp:
        script, record = _fake_antigravity(tmp, [_tool_event("search_web"), _result_event()])
        out = asyncio.run(_antigravity(tmp, script).complete("検索", tools={"websearch": True}))
        assert out == "回答"
        with open(record) as f:
            argv = json.load(f)["argv"]
        assert argv[argv.index("--agent") + 1] == "aisync-demo-web"


def test_antigravity_rejects_reply_if_forbidden_tool_ran():
    with tempfile.TemporaryDirectory() as tmp:
        for tool, tools in (("run_command", None), ("search_web", None), ("view_file", {"websearch": True})):
            script, _ = _fake_antigravity(tmp, [_tool_event(tool), _result_event("uid=1000")])
            _assert_provider_error(_antigravity(tmp, script).complete("ls して", tools=tools), tool)


def test_antigravity_rejects_reply_if_action_was_denied():
    with tempfile.TemporaryDirectory() as tmp:
        script, _ = _fake_antigravity(tmp, [_result_event("途中", denied_actions=[{"action": "command"}])])
        _assert_provider_error(_antigravity(tmp, script).complete("x"), "command")


def test_antigravity_surfaces_upstream_errors():
    with tempfile.TemporaryDirectory() as tmp:
        script, _ = _fake_antigravity(tmp, [_result_event("", status="ERROR", error="quota exhausted")], exit_code=3)
        _assert_provider_error(_antigravity(tmp, script).complete("x"), "quota exhausted")
        # 結果イベントが無くても理由が空にならない
        script, _ = _fake_antigravity(tmp, [], exit_code=1, stderr="auth failed")
        _assert_provider_error(_antigravity(tmp, script).complete("x"), "auth failed")
        # 空応答は成功扱いにしない
        script, _ = _fake_antigravity(tmp, [_result_event("")])
        _assert_provider_error(_antigravity(tmp, script).complete("x"), "exit=0")


def test_antigravity_timeout_kills_process():
    with tempfile.TemporaryDirectory() as tmp:
        script, _ = _fake_antigravity(tmp, [], sleep=60)
        # 実装は timeout + 5 秒で打ち切る
        p = _antigravity(tmp, script, timeout=-4.5)
        started = time.monotonic()
        _assert_provider_error(p.complete("x"), "応答がありません")
        assert time.monotonic() - started < 10


def test_antigravity_hourly_call_cap():
    with tempfile.TemporaryDirectory() as tmp:
        script, record = _fake_antigravity(tmp, [_result_event()])
        p = _antigravity(tmp, script, max_calls_per_hour=1)
        assert asyncio.run(p.complete("1回目")) == "回答"
        os.remove(record)
        _assert_provider_error(p.complete("2回目"), "上限")
        assert not os.path.exists(record), "上限超過でも CLI が起動された"


if __name__ == "__main__":
    tests = [v for k, v in dict(globals()).items() if k.startswith("test_") and callable(v)]
    for t in tests:
        t()
        print("ok", t.__name__)
    print(f"{len(tests)} passed")
