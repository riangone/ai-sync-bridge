"""
リクエスト本文のサイズ上限。Pydantic の検証は本文を読み終えてからしか動かないので、その手前で止める。

Content-Length を見るだけだと chunked 送信で素通りするため、受信しながらも数える。
FastAPI は本文読み取り中の例外を 400 に丸めるが、HTTPException はそのまま通すので 413 で返る。
"""
from fastapi import HTTPException
from starlette.responses import JSONResponse

DEFAULT_MAX_BODY = 256 * 1024
# 写真や PDF を受ける OCR だけ大きくする。multipart の区切り分の余裕を含む。
OCR_MAX_BODY = 10 * 1024 * 1024 + 64 * 1024
_LARGE_BODY_PATHS = {"/api/ocr": OCR_MAX_BODY}
_MESSAGE = "リクエストが大きすぎます"


def _limit_for(path: str) -> int:
    return _LARGE_BODY_PATHS.get(path.rstrip("/"), DEFAULT_MAX_BODY)


class BodySizeLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        limit = _limit_for(scope["path"])
        declared = dict(scope["headers"]).get(b"content-length")
        if declared is not None and declared.isdigit() and int(declared) > limit:
            await JSONResponse({"detail": _MESSAGE}, status_code=413)(scope, receive, send)
            return
        received = 0

        async def counting_receive():
            nonlocal received
            message = await receive()
            if message["type"] == "http.request":
                received += len(message.get("body", b""))
                if received > limit:
                    raise HTTPException(status_code=413, detail=_MESSAGE)
            return message

        await self.app(scope, counting_receive, send)
