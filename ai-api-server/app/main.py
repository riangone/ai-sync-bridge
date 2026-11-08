"""
AI-Sync Bridge - AI API Server エントリポイント
FastAPI + 純粋な HTML/JS/CSS フロント (Chrome拡張 / デモレガシーシステム) 向け。
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.public_errors import AI_RATE_LIMITED, AI_UNAVAILABLE, log_upstream
from app.services.ai_client import AIProviderError, AIRateLimitError
from app.services.rate_limit import ClientContextMiddleware
from app.services.request_limits import BodySizeLimitMiddleware
from app.domains import register_routers

settings = get_settings()

docs_kwargs = {} if settings.expose_api_docs else {"docs_url": None, "redoc_url": None, "openapi_url": None}
app = FastAPI(title=settings.app_name, version="1.0.0", **docs_kwargs)

app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(ClientContextMiddleware)

# API は Cookie を使わないので credentials は不要。ブラウザ以外(curl 等)は CORS では止まらない。
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_origin_regex=settings.cors_origin_regex,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["*"],
)

# コア(業種非依存) + AISB_DOMAINS で選択した業種ドメインのルーターを登録(app/domains.py)
enabled_domains = register_routers(app, settings.domains)


@app.on_event("startup")
async def _start_bridge_scheduler():
    """ブリッジ profile の sync.interval_sec > 0 なら定期差分同期を開始する。"""
    import asyncio

    from app.deps import get_bridge

    bridge = get_bridge()
    # 埋め込みモデルを切り替えた直後は、前のモデルのベクトルが混ざって「静かに外れる」検索に
    # なる。起動時に追いつかせる(非同期なので起動自体は待たせない。待ち件数は /status の
    # embedder_mixed で見える)。
    if bridge.store.count_other_embedder(bridge.engine.embedder_id):
        app.state.embedder_backfill = asyncio.create_task(bridge.reembed_stale())
    if bridge.sync_interval > 0:
        app.state.bridge_task = asyncio.create_task(bridge.run_periodic())


@app.exception_handler(AIProviderError)
async def ai_provider_error_handler(request: Request, exc: AIProviderError):
    """chat/assistant/insight等、個別にAIProviderErrorをキャッチしていない呼び出し元の
    最終防波堤(fail loud)。以前はプロバイダ側で例外を文字列(例: "[opencode-error-fallback] ...")
    に変換してそのまま正常応答として返していたため、AI障害時に「もっともらしい誤回答」が
    ユーザーへ表示されるサイレント破損があった(ai_client.py参照)。ここで一律502に変換する
    ことで、AI応答とエラーが型として絶対に混同されないことを保証する。
    個々のservice(nlsql/web_search等)で縮退応答が業務的に妥当な場合は、そちら側で
    個別にキャッチしてこのハンドラに到達させない。"""
    log_upstream("ai provider error", exc)
    return JSONResponse(status_code=502, content={"error": True, "message": AI_UNAVAILABLE})


@app.exception_handler(AIRateLimitError)
async def ai_rate_limit_handler(request: Request, exc: AIRateLimitError):
    return JSONResponse(status_code=429, content={"error": True, "message": AI_RATE_LIMITED})


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
