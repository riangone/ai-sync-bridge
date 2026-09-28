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
    # 2026-09-08: laguna-s-2.1-free も上流で401("not supported")に廃止済みと実地確認
    # (north-mini-code-free/ling-3.0-flash-free/laguna-s-2.1-free/deepseek-v4-flash-free
    # の4つ全滅、nemotron-3-ultra-free は502で不安定)。現時点で安定して疎通するのは
    # big-pickle と mimo-v2.5-free の2つのみ(各2回連続成功を確認)。テキスト専用の
    # big-pickle に変更。無料枠モデルは今後も予告なく廃止されるため、動作しなくなったら
    # 同様に /config/providers の全モデルを実地プローブし直すこと(status="active"表示は
    # 信用できない)。
    opencode_model_id: str = os.getenv("OPENCODE_MODEL_ID", "big-pickle")
    # 2026-09-18: 「AI呼び出しが不調」と報告あり調査。今回はモデル廃止(401)ではなく、
    # ローカルの opencode CLI バイナリが古い(1.15.3)ままだったことが原因と実地確認。
    # 無料枠(Zen)側が「OpenCode 1.18.0 以降が必要」という426 UpgradeRequiredエラーを返し、
    # big-pickle/mimo-v2.5-free含む全モデルが失敗していた(モデル自体は生きていた)。
    # `sudo npm i -g opencode-ai@latest`(→1.18.31)でCLIを更新し、稼働中の`opencode serve`
    # プロセス(古いバイナリをメモリに保持したまま)を再起動して復旧。3インスタンス
    # (5011/5021/5031)の /api/chat 実呼び出しでも復旧確認済み。
    # 教訓: このエラー系は「モデルの生死(401)」だけでなく「ローカルCLIのバージョン(426)」
    # も疑うこと。まず `opencode --version` とエラー本文(UpgradeRequired等)を確認する。
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
    # インスタンスかを表す。ai-api-server はERP版/ディーラー版/不動産仲介版で全く同一の
    # コードをプロセスだけ分けて動かす構成のため("同一コードから業種非依存で追従できる"
    # ことの実証)、これを外部から明示しないと (1) 各インスタンスが同じSQLiteファイルに
    # 書き込んで壊し合う、(2) 業態と食い違うダミーデータ(山田商事等)が出続ける、という
    # 2つの相互干渉が起きる。値は "erp" | "dealer" | "realestate"。
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
