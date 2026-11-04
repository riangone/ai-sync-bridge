"""
送信元 IP の判定とスライディングウィンドウの回数制限(公開デモの LLM 消費を抑える)。

LLM を呼ぶ経路は多く、エンドポイントごとに制限を書くと漏れるので、ClientContextMiddleware が
リクエストの送信元を contextvar に置き、AI プロバイダの呼び出し口(ai_client.
PerClientLimitedProvider)で数える。バックグラウンド処理と、前段プロキシを通らないローカルの
呼び出しは送信元なし扱いで対象外(プロバイダ全体の上限は別途かかる)。
"""
from __future__ import annotations

import threading
import time
from collections import OrderedDict, deque
from contextvars import ContextVar

from starlette.requests import Request

_LOOPBACK = {"127.0.0.1", "::1"}

current_client: ContextVar[str | None] = ContextVar("aisb_current_client", default=None)


def client_ip(request: Request) -> str:
    """送信元 IP。X-Forwarded-For はローカルの前段プロキシ経由のときだけ信用し、
    そのプロキシが付けた末尾の値を使う(先頭側はクライアントが偽装できる)。"""
    peer = request.client.host if request.client else ""
    if peer in _LOOPBACK:
        forwarded = request.headers.get("x-forwarded-for", "")
        if forwarded:
            return forwarded.split(",")[-1].strip()
    return peer or "unknown"


class ClientContextMiddleware:
    """BaseHTTPMiddleware は contextvar がエンドポイントへ伝わらないので ASGI で直接書く。"""

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        ip = client_ip(Request(scope))
        token = current_client.set(None if ip in _LOOPBACK else ip)
        try:
            await self.app(scope, receive, send)
        finally:
            current_client.reset(token)


class SlidingWindowLimiter:
    """キーごとのスライディングウィンドウ。キー数は上限を超えると古い順に捨てる。"""

    def __init__(self, limit: int, window_sec: float, max_keys: int = 10000):
        self.limit = limit
        self.window = window_sec
        self.max_keys = max_keys
        self._hits: OrderedDict[str, deque[float]] = OrderedDict()
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            hits = self._hits.setdefault(key, deque())
            self._hits.move_to_end(key)
            while hits and now - hits[0] >= self.window:
                hits.popleft()
            while len(self._hits) > self.max_keys:
                self._hits.popitem(last=False)
            if len(hits) >= self.limit:
                return False
            hits.append(now)
            return True
