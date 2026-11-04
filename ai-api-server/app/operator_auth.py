"""
運用者向けエンドポイントの認可(/api/admin, /api/search)。

通過できるのは次のどちらかだけ:
  - リバースプロキシを経由しない、サーバー自身からのアクセス
  - 環境変数 AISB_API_ADMIN_KEY と一致する X-AISB-Admin-Key ヘッダ付きのアクセス

判定方法は aisb_embed の /aisb-embed/toggle と同じ。キー未設定なら公開経路からは常に拒否する。
"""
import hmac
import ipaddress
import os

from fastapi import HTTPException, Request

_ADMIN_KEY_ENV = "AISB_API_ADMIN_KEY"
# 同一マシンの Caddy からの転送も接続元は 127.0.0.1 になるため、接続元だけでは公開経路と区別できない。
# Caddy は X-Forwarded-For を常に付けるので、これらのヘッダがあれば公開経路として扱う。
_PROXY_HEADERS = ("x-forwarded-for", "x-forwarded-host", "x-forwarded-proto", "x-forwarded-prefix", "x-real-ip", "forwarded")


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


def require_operator(request: Request) -> None:
    if not (_is_local_direct(request) or _has_admin_key(request)):
        raise HTTPException(status_code=403, detail="forbidden")
