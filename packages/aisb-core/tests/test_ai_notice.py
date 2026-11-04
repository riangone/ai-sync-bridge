"""AI パネル注意書きの注入テスト。ネットワーク不要。

実行: <demo>/.venv/bin/python packages/aisb-core/tests/test_ai_notice.py   (pytest でも可)
"""
import json
import tempfile
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.testclient import TestClient

from aisb_embed import config
from aisb_embed.middleware import AisbEmbedMiddleware
from aisb_embed.profile import EmbedProfile

REPO = Path(__file__).resolve().parents[3]


def _page(ai_notice):
    config.set_state_file(Path(tempfile.mkdtemp()) / "state.json")
    app = FastAPI()
    app.add_middleware(AisbEmbedMiddleware, profile=EmbedProfile(profile_dir=Path("."), ai_notice=ai_notice))

    @app.get("/")
    def index():
        return HTMLResponse("<html><body>x</body></html>")

    return TestClient(app).get("/").text


def test_notice_is_injected():
    html = _page({"text": "注意", "link_label": "規約", "link_url": "https://example.com/p"})
    assert '"text": "注意"' in html
    assert "https://example.com/p" in html


def test_no_notice_by_default():
    assert "window.AISB_AI_NOTICE = null;" in _page(None)


def test_notice_cannot_close_script_tag():
    html = _page({"text": "</script><img src=x onerror=alert(1)>"})
    assert "<img" not in html
    assert "\\u003c/script>" in html


def test_every_demo_shows_notice_with_policy_link():
    demos = sorted(REPO.glob("demo-legacy-system*"))
    assert demos
    for demo in demos:
        notice = json.loads((demo / "aisb_profile/profile.json").read_text(encoding="utf-8"))["ai_notice"]
        assert notice["text"] and notice["link_url"] == "https://0101.click/privacy.html"
        assert notice["link_url"] in (demo / "templates/base.html").read_text(encoding="utf-8")


if __name__ == "__main__":
    for name, fn in list(globals().items()):
        if name.startswith("test_"):
            fn()
            print("ok", name)
