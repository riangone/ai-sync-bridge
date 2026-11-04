"""
aisb_embed 自身の管理用エンドポイント。

/aisb-embed/admin は「サイドバーが無効化されていて画面上にトグルUIが
存在しない」状態でも常に直接アクセスできる、有効/無効の唯一の入口。
レガシー側のナビゲーション(base.html)には一切リンクを追加していない
(=ここも無改造)。

切り替えを実行できるのは次のどちらかだけ(閲覧は誰でもできる):
  - リバースプロキシを経由しない、サーバー自身からのアクセス
  - 環境変数 AISB_EMBED_ADMIN_KEY と一致する X-AISB-Admin-Key ヘッダ付きのアクセス
"""
import hmac
import html
import ipaddress
import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from . import config

router = APIRouter(prefix="/aisb-embed", tags=["aisb-embed"])
# mount() が EmbedProfile.system_label で上書きする(管理画面の説明文用)
SYSTEM_LABEL = "レガシーERP"


_ADMIN_KEY_ENV = "AISB_EMBED_ADMIN_KEY"
# 同一マシンの Caddy からの転送も接続元は 127.0.0.1 になるため、接続元だけでは公開経路と区別できない。
# Caddy は X-Forwarded-For を常に付けるので、これらのヘッダがあれば公開経路として扱う。
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-prefix", "x-real-ip", "forwarded")


class ToggleBody(BaseModel):
    enabled: bool


def _is_local_direct(request: Request) -> bool:
    if any(h in request.headers for h in _PROXY_HEADERS):
        return False
    try:
        return ipaddress.ip_address(request.client.host if request.client else "").is_loopback
    except ValueError:
        return False


def _has_admin_key(request: Request) -> bool:
    expected = os.environ.get(_ADMIN_KEY_ENV, "")
    given = request.headers.get("x-aisb-admin-key", "")
    return bool(expected) and hmac.compare_digest(given.encode("utf-8"), expected.encode("utf-8"))


@router.get("/status")
def status():
    return {
        "enabled": config.is_enabled(),
        "env_override": config.env_override(),
        "env_var": "AISB_EMBED_ENABLED" if config.env_override() is not None else None,
    }


@router.post("/toggle")
def toggle(body: ToggleBody, request: Request):
    if not (_is_local_direct(request) or _has_admin_key(request)):
        raise HTTPException(status_code=403, detail="forbidden")
    config.set_enabled(body.enabled)
    return status()


@router.get("/admin", response_class=HTMLResponse)
def admin_page(request: Request):
    # Caddyのサブパス公開(strip_prefix)経由でアクセスされた場合、素の"/aisb-embed/toggle"
    # へfetchすると別システム(同一ドメイン配下の別プロセス)を誤って叩いてしまうため、
    # 常にX-Forwarded-Prefixを踏まえた絶対パスで自分自身を叩く。
    prefix = request.headers.get("x-forwarded-prefix", "")
    # ブラウザのボタンはキーを送れないので、キーの有無にかかわらず表示するのはサーバー自身からのアクセスだけ
    can_toggle = _is_local_direct(request)
    locked = config.env_override() is not None
    enabled = config.is_enabled()
    lock_notice = (
        f"<p style='color:#d03b3b'>環境変数 AISB_EMBED_ENABLED="
        f"{os.environ.get('AISB_EMBED_ENABLED')!r} が設定されているため、"
        f"下のボタンでの切り替えは保存はされますが実際の有効/無効には反映されません"
        f"(env変数を外すかサーバー起動時の設定を変更してください)。</p>"
        if locked
        else ""
    )
    controls = (
        f"""<button id="toggle-btn">{"無効化する" if enabled else "有効化する"}</button>
  <script>
    document.getElementById("toggle-btn").addEventListener("click", async () => {{
      const nowEnabled = document.getElementById("state").classList.contains("on");
      await fetch("{html.escape(prefix, quote=True)}/aisb-embed/toggle", {{
        method: "POST",
        headers: {{ "Content-Type": "application/json" }},
        body: JSON.stringify({{ enabled: !nowEnabled }}),
      }});
      location.reload();
    }});
  </script>"""
        if can_toggle
        else '<p class="desc">公開経路からは切り替えできません。サーバー上で操作してください。</p>'
    )
    return f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<title>AI-Sync Bridge 埋め込み管理</title>
<style>
  body {{ font-family: -apple-system, "Segoe UI", "Hiragino Sans", sans-serif; max-width: 520px; margin: 60px auto; color: #222; }}
  h1 {{ font-size: 18px; color: #17497e; }}
  .state {{ display: inline-block; padding: 4px 10px; border-radius: 4px; font-weight: 600; }}
  .state.on {{ background: #e6f7e6; color: #0ca30c; }}
  .state.off {{ background: #fdecea; color: #d03b3b; }}
  button {{ background: #2a78d6; color: #fff; border: none; border-radius: 4px; padding: 8px 16px; cursor: pointer; font-size: 13px; margin-top: 12px; }}
  button.off {{ background: #888; }}
  p.desc {{ color: #555; font-size: 13px; line-height: 1.6; }}
</style>
</head>
<body>
  <h1>AI-Sync Bridge 埋め込み機能</h1>
  <p class="desc">
    {html.escape(SYSTEM_LABEL)}全画面に、Chrome拡張機能と同じAIサイドバー(業務データ閲覧/AIチャット/
    予測分析/ワークフロー/通知/管理)を直接埋め込むアドオン機能です。
    レガシー側のテンプレート/ルーティングは一切変更していません
    (main.py への追加は起動時の2行のみ)。
  </p>
  <p>現在の状態: <span id="state" class="state {"on" if enabled else "off"}">{"有効" if enabled else "無効"}</span></p>
  {lock_notice}
  {controls}
</body>
</html>"""
