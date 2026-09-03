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
    # 2026-08-19: デフォルトだった north-mini-code-free が上流(opencode Zen)で401廃止済みと判明
    # (実地プローブ済み)。動作確認済みの deepseek-v4-flash-free に変更。ローカルの
    # /config/providers キャッシュは古く north-mini-code-free を "active" と誤表示するため注意。
    opencode_provider_id: str = os.getenv("OPENCODE_PROVIDER_ID", "opencode")
    # 2026-08-21: deepseek-v4-flash-free は上流で無料枠終了(401 "Free promotion has ended")
    # を実地確認。/config/providers のキャッシュは全モデル status="active" と誤表示する
    # ため、実際に session/message を叩いて info.error が返らないことを個別に検証した
    # (north-mini-code-free/ling-3.0-flash-free/deepseek-v4-flash-free は401、
    # laguna-s-2.1-free/big-pickle/nemotron-3-ultra-free は疎通OK)。websearchツール込みの
    # 実検索でも動作確認済みの laguna-s-2.1-free に変更。
    opencode_model_id: str = os.getenv("OPENCODE_MODEL_ID", "laguna-s-2.1-free")
    # 既定モデル(deepseek-v4-flash-free)は capabilities.input.image=false でvision非対応
    # (2026-08-21 GET /config/providers で実地確認)。画像入力が要る用途(OCR等)は別途
    # image=true のモデルを明示指定する。無料枠で確認できたのは mimo-v2.5-free のみ
    # (image/audio/video対応、pdfは非対応)。
    opencode_vision_model_id: str = os.getenv("OPENCODE_VISION_MODEL_ID", "mimo-v2.5-free")

    # ベクトル検索エンジン選択 (8.3): sqlite-vec -> ann -> brute-force
    vector_backend: str = os.getenv("AISB_VECTOR_BACKEND", "brute-force")

    # デモレガシーシステム(6章)のベースURL。自然言語→構造化フィルタ検索(5.4.11差分実装)が
    # 対象データ(13エンティティ)を読みに行くためだけに使う。レガシー側はこの呼び出しの
    # 存在を一切知らない(読み取り専用の既存 /api/{entity}/list を叩くだけ)。
    legacy_base_url: str = os.getenv("AISB_LEGACY_BASE_URL", "http://localhost:5010")

    # このプロセスがどの業種ドメイン(=どのレガシーシステム)向けの ai-api-server
    # インスタンスかを表す。ai-api-server はERP版/ディーラー版で全く同一のコードを
    # プロセスだけ分けて動かす構成のため("同一コードから業種非依存で追従できる"ことの
    # 実証)、これを外部から明示しないと (1) 両インスタンスが同じSQLiteファイルに
    # 書き込んで壊し合う、(2) ディーラー側なのにERP風ダミーデータ(山田商事等)が
    # 出続ける、という2つの相互干渉が起きる。値は "erp" | "dealer"。
    instance: str = os.getenv("AISB_INSTANCE", "erp")

    # DemoDataStore(demo_mode時の会話履歴/受注等)の永続化先。未指定時は instance ごとに
    # 別ファイルをデフォルトにすることで、env設定を忘れて2インスタンスを同じディレクトリ
    # から起動しても取り違え/相互上書きが起きないようにしている(データ層の物理分離)。
    db_path: str = os.getenv(
        "AISB_DB_PATH",
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "data", f"aisb_{instance}.db"),
    )

    # CORS: Chrome拡張(content script)からのアクセスを許可
    cors_origins: list[str] = ["*"]


@lru_cache
def get_settings() -> Settings:
    return Settings()
