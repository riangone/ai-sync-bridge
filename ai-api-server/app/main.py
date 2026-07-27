"""
AI-Sync Bridge - AI API Server エントリポイント
FastAPI + 純粋な HTML/JS/CSS フロント (Chrome拡張 / デモレガシーシステム) 向け。
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import get_settings
from app.routers import (
    admin,
    analytics,
    chat,
    cross_analysis,
    customers,
    nlsql,
    notifications,
    ocr,
    orders,
    search,
    workflows,
)

settings = get_settings()

app = FastAPI(title=settings.app_name, version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(customers.router)
app.include_router(orders.router)
app.include_router(chat.router)
app.include_router(ocr.router)
app.include_router(search.router)
app.include_router(analytics.router)
app.include_router(workflows.router)
app.include_router(notifications.router)
app.include_router(admin.router)
app.include_router(nlsql.router)
app.include_router(cross_analysis.router)


@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "demo_mode": settings.demo_mode,
        "ai_provider": settings.ai_provider,
        "vector_backend": settings.vector_backend,
    }


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("app.main:app", host=settings.host, port=settings.port, reload=True)
