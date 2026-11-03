"""
AI-Sync Bridge - AI API Server エントリポイント
FastAPI + 純粋な HTML/JS/CSS フロント (Chrome拡張 / デモレガシーシステム) 向け。
"""
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.config import get_settings
from app.services.ai_client import AIProviderError
from app.domains import register_routers

settings = get_settings()

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
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
    return JSONResponse(
        status_code=502,
        content={
            "error": True,
            "message": "AIサービスが一時的に利用できません。しばらくしてから再度お試しください。",
            "provider": exc.provider,
            "detail": str(exc.original),
        },
    )


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "ai_provider": settings.ai_provider,
        "vector_backend": settings.vector_backend,
        "domains": enabled_domains,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
