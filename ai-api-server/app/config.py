"""
AI-Sync Bridge - AI API Server 設定
demo/prod デュアルモードを1フラグで透過的に切り替える。
Controller(routers)層はこのフラグを意識せず、Service層のみが分岐する。
"""
import os
from functools import lru_cache
from pydantic import BaseModel


class Settings(BaseModel):
    app_name: str = "AI-Sync Bridge API Server"
    host: str = "0.0.0.0"
    port: int = 5011

    # デモ/本番デュアルモード（8.1: demoMode フラグ）
    demo_mode: bool = os.getenv("AISB_DEMO_MODE", "true").lower() == "true"

    # マルチAIプロバイダ抽象化 (8.2)
    ai_provider: str = os.getenv("AISB_AI_PROVIDER", "mock")  # mock|opencode|openai|gemini
    openai_api_key: str | None = os.getenv("OPENAI_API_KEY")
    gemini_api_key: str | None = os.getenv("GEMINI_API_KEY")
    opencode_endpoint: str = os.getenv("OPENCODE_ENDPOINT", "http://localhost:4096")
    # opencode serve が公開する実APIのモデル指定 (GET /config/providers で確認: 無料枠モデル)
    opencode_provider_id: str = os.getenv("OPENCODE_PROVIDER_ID", "opencode")
    opencode_model_id: str = os.getenv("OPENCODE_MODEL_ID", "north-mini-code-free")

    # ベクトル検索エンジン選択 (8.3): sqlite-vec -> ann -> brute-force
    vector_backend: str = os.getenv("AISB_VECTOR_BACKEND", "brute-force")

    # デモレガシーシステム(6章)のベースURL。自然言語→構造化フィルタ検索(5.4.11差分実装)が
    # 対象データ(13エンティティ)を読みに行くためだけに使う。レガシー側はこの呼び出しの
    # 存在を一切知らない(読み取り専用の既存 /api/{entity}/list を叩くだけ)。
    legacy_base_url: str = os.getenv("AISB_LEGACY_BASE_URL", "http://localhost:5010")

    # CORS: Chrome拡張(content script)からのアクセスを許可
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
