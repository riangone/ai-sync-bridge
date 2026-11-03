"""
マルチAIプロバイダ抽象化層 (仕様 8.2: AiHttpClient)
OpenCode CLI / OpenAI / Gemini / Mock を単一インターフェースで吸収する。
呼び出し側 (chat_service, search_service) はプロバイダの違いを意識しない。
"""
import base64
from abc import ABC, abstractmethod
import httpx
from app.config import Settings
from app.services.ai_guard import GUARDRAIL_SYSTEM_PROMPT, build_tool_flags, redact_output


class AIProviderError(Exception):
    """AIプロバイダ呼び出しの失敗(タイムアウト・HTTPエラー・上流モデル側エラー等)を表す専用例外。

    旧実装は失敗時に "[xxx-error-fallback] ..." という文字列を正常応答と同じ型(str)で
    returnしていたため、呼び出し側(chat/assistant/insight/nlsql/web_search の各service)が
    この文字列プレフィックスを個別に認識しない限り、エラー内容がそのまま「AIの回答」として
    ユーザーに表示されてしまっていた(サイレント破損)。例外に変えることで、キャッチし忘れた
    呼び出し側は握りつぶさずに例外を伝播させる(fail loud)。呼び出し側は業務要件に応じて
    (a) キャッチして構造化エラー/縮退応答を返すか、(b) キャッチせずFastAPIの例外処理層
    (app.main の exception_handler)に委ねて502として返すかを選べる。
    """

    def __init__(self, provider: str, original: Exception | str):
        self.provider = provider
        self.original = original
        super().__init__(f"[{provider}] AIプロバイダ呼び出しに失敗しました: {original}")


class AiProvider(ABC):
    name: str
    # 埋め込みベクトルの互換性ID。これが変わるとブリッジは全文書を再埋め込みする。
    embedder_id: str = "unknown"
    supports_vision: bool = False

    @abstractmethod
    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...

    async def complete_vision(self, prompt: str, image_bytes: bytes, mime: str) -> str:
        """画像を添付してAIに問い合わせる。既定は非対応(呼び出し側は supports_vision を
        先に確認する設計だが、直接呼ばれた場合も安全に倒せるようここで明示的に弾く)。"""
        raise NotImplementedError(f"{self.name} プロバイダは画像入力(vision)に対応していません")


class MockProvider(AiProvider):
    """デモモード/APIキー未設定時のフォールバック。決定論的な擬似応答を返す。"""
    name = "mock"
    embedder_id = "ngram-hash-64"

    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str:
        return f"[mock-ai] 「{prompt[:50]}」について回答します。これはデモ応答です。"

    async def embed(self, text: str) -> list[float]:
        # 3段階フォールバックの最終段: n-gram ハッシュベースの擬似埋め込み
        dim = 64
        vec = [0.0] * dim
        for i, ch in enumerate(text):
            vec[(ord(ch) + i) % dim] += 1.0
        norm = sum(v * v for v in vec) ** 0.5 or 1.0
        return [v / norm for v in vec]


class OpenAIProvider(AiProvider):
    name = "openai"
    embedder_id = "openai:text-embedding-3-small"

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str:
        # OpenAI chat completions APIはopencodeの{"websearch": true}形式のtools指定と
        # 互換性が無いため、ここではtoolsを無視する(素のchat completionのみ対応)。
        # 安全ガード(ai_guard)の system を必ず先頭に置く。履歴側の system は業務文脈として後ろに続ける。
        messages = [{"role": "system", "content": GUARDRAIL_SYSTEM_PROMPT}] + (history or []) + [{"role": "user", "content": prompt}]
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": "gpt-4o-mini", "messages": messages},
                )
                resp.raise_for_status()
                return redact_output(resp.json()["choices"][0]["message"]["content"])
            except Exception as exc:
                raise AIProviderError(self.name, exc) from exc

    async def embed(self, text: str) -> list[float]:
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    "https://api.openai.com/v1/embeddings",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": "text-embedding-3-small", "input": text},
                )
                resp.raise_for_status()
                return resp.json()["data"][0]["embedding"]
            except Exception:
                return await MockProvider().embed(text)


class GeminiProvider(AiProvider):
    name = "gemini"
    embedder_id = "ngram-hash-64"  # embed() は MockProvider へ委譲している

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str:
        # Gemini generateContent APIも同様にopencode独自のtools形式とは非互換のため無視する。
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={self.api_key}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(url, json={
                    "systemInstruction": {"parts": [{"text": GUARDRAIL_SYSTEM_PROMPT}]},
                    "contents": [{"parts": [{"text": prompt}]}],
                })
                resp.raise_for_status()
                data = resp.json()
                return redact_output(data["candidates"][0]["content"]["parts"][0]["text"])
            except Exception as exc:
                raise AIProviderError(self.name, exc) from exc

    async def embed(self, text: str) -> list[float]:
        return await MockProvider().embed(text)


class OpenCodeProvider(AiProvider):
    """ローカル OpenCode CLI サーバー (`opencode serve`, 既定 localhost:4096) を叩くプロバイダ。

    注意: 実際の OpenCode サーバーAPIは `/chat` のような単純なチャットエンドポイントを
    公開していない（誤って想定していた旧実装は `/doc` の OpenAPI 定義で未定義と判明し、
    実際にはSPAのcatch-allルートにフォールバックしHTMLが返っていた＝サイレント破損）。
    実APIは「セッション作成 → セッションにメッセージ投稿 → parts配列からtext partを抽出」
    という3段階の流れになっている（`GET /doc` で確認済み）:
      POST /session                              -> {"id": "ses_..."}
      POST /session/{sessionID}/message
           body: {"model": {"providerID","modelID"}, "parts": [{"type":"text","text":...}]}
           -> {"info": AssistantMessage, "parts": [Part, ...]}
    会話履歴(history)はこちら側(demo_data.py)のセッション管理と別物なので、
    OpenCode側にも二重にセッションを持たせず、呼び出しごとに使い捨てセッションを
    作成し、history をプロンプト先頭に文脈として埋め込む設計にした。
    """
    name = "opencode"
    embedder_id = "ngram-hash-64"  # embed() は MockProvider へ委譲している

    # セッション単位の権限: 全ツール deny、websearch のみ allow (後勝ち評価)。
    # opencode 側設定(ops/opencode/aisync-opencode.json)でも deny 済みだが二重に塞ぐ。
    _SESSION_PERMISSION = [
        {"permission": "*", "pattern": "*", "action": "deny"},
        {"permission": "websearch", "pattern": "*", "action": "allow"},
    ]

    def __init__(self, endpoint: str, provider_id: str, model_id: str, vision_model_id: str | None = None, agent: str = "aisync-demo"):
        # 既定モデル(model_id)はテキスト専用のことが多いため vision_model_id を別枠で持つ。
        # 未指定(None)の場合は complete_vision() 自体を非サポート扱いにする(誤って
        # テキスト専用モデルに画像を送って静かに無視されるより、明示的に弾く方が安全)。
        self.endpoint = endpoint.rstrip("/")
        self.provider_id = provider_id
        self.model_id = model_id
        self.vision_model_id = vision_model_id
        self.supports_vision = bool(vision_model_id)
        # ops/opencode/aisync-opencode.json で定義した、ツール無し・安全プロンプト付きの専用エージェント。
        # 既定の build エージェント(bash等フル装備)を絶対に使わないよう常に明示する。
        # 設定が読み込まれていない opencode に繋いだ場合はエージェント不明で失敗する(fail closed)。
        self.agent = agent

    def _session_body(self) -> dict:
        return {"title": "aisync-demo", "agent": self.agent, "permission": self._SESSION_PERMISSION}

    def _assert_no_forbidden_tool_use(self, parts: list[dict]) -> None:
        """許可外ツールが1つでも実行されていたら応答ごと破棄する(設定が効いていない異常系の検知)。"""
        for p in parts:
            if p.get("type") == "tool" and p.get("tool") not in ("websearch",):
                raise AIProviderError(self.name, f"許可されていないツール実行を検知したため応答を破棄しました: {p.get('tool')}")

    def _build_prompt(self, prompt: str, history: list[dict] | None) -> str:
        if not history:
            return prompt
        lines = [f"{h.get('role', 'user')}: {h.get('content', '')}" for h in history]
        lines.append(f"user: {prompt}")
        return "これまでの会話:\n" + "\n".join(lines)

    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str:
        """tools: {"websearch": true} のように明示指定すると、そのツールだけを有効化する。
        ai_guard.ALLOWED_TOOLS 以外(bash/read/webfetch等)は要求されても常に無効。
        未指定時は全ツール無効(旧実装は「未指定=全ツール利用可」で、チャットから実サーバーの
        bash が実行された。2026-10-26 インシデント)。"""
        full_prompt = self._build_prompt(prompt, history)
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                session_resp = await client.post(f"{self.endpoint}/session", json=self._session_body())
                session_resp.raise_for_status()
                session_id = session_resp.json()["id"]

                body: dict = {
                    "model": {"providerID": self.provider_id, "modelID": self.model_id},
                    "agent": self.agent,
                    "system": GUARDRAIL_SYSTEM_PROMPT,
                    "tools": build_tool_flags(tools),
                    "parts": [{"type": "text", "text": full_prompt}],
                }

                msg_resp = await client.post(
                    f"{self.endpoint}/session/{session_id}/message",
                    json=body,
                )
                msg_resp.raise_for_status()
                msg_json = msg_resp.json()
                # HTTPは200でも、上流(opencode Zen)のモデル側エラー(無料枠終了401等)は
                # info.error に埋め込まれて返ってくる仕様(2026-08-21実地確認)。ここを
                # 見ないと「エラーなのに空文字列成功扱い」でサイレント失敗する。
                error = (msg_json.get("info") or {}).get("error")
                if error:
                    message = (error.get("data") or {}).get("message") or error.get("name") or str(error)
                    raise AIProviderError(self.name, message)
                parts = msg_json.get("parts", [])
                self._assert_no_forbidden_tool_use(parts)
                text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
                return redact_output(text) or "[opencode-empty-response]"
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(self.name, exc) from exc

    async def complete_vision(self, prompt: str, image_bytes: bytes, mime: str) -> str:
        """画像を FilePart(type=file, url=data URL) として添付し、vision対応モデルに
        問い合わせる(`GET /doc` の FilePartInput スキーマで url が data URL 可であることを
        確認済み)。model_id ではなく vision_model_id を明示指定する(既定モデルは
        capabilities.input.image=false のことが多く、画像を送っても無視されるため)。"""
        if not self.vision_model_id:
            raise NotImplementedError(
                "OPENCODE_VISION_MODEL_ID が未設定のため画像入力に対応できません"
            )
        data_url = f"data:{mime};base64,{base64.b64encode(image_bytes).decode()}"
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                session_resp = await client.post(f"{self.endpoint}/session", json=self._session_body())
                session_resp.raise_for_status()
                session_id = session_resp.json()["id"]

                msg_resp = await client.post(
                    f"{self.endpoint}/session/{session_id}/message",
                    json={
                        "model": {"providerID": self.provider_id, "modelID": self.vision_model_id},
                        "agent": self.agent,
                        "system": GUARDRAIL_SYSTEM_PROMPT,
                        "tools": build_tool_flags(None),
                        "parts": [
                            {"type": "file", "mime": mime, "url": data_url},
                            {"type": "text", "text": prompt},
                        ],
                    },
                )
                msg_resp.raise_for_status()
                parts = msg_resp.json().get("parts", [])
                self._assert_no_forbidden_tool_use(parts)
                text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
                return redact_output(text) or "[opencode-empty-response]"
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(self.name, exc) from exc

    async def embed(self, text: str) -> list[float]:
        # OpenCodeサーバーは埋め込み専用APIを公開していないため、
        # 3段階フォールバック(仕様8.2)の末端である n-gram 擬似埋め込みに委譲する。
        return await MockProvider().embed(text)


def build_ai_provider(settings: Settings) -> AiProvider:
    """設定に応じてプロバイダを選択。キー未設定/接続失敗は呼び出し側でMockにフォールバック可。"""
    if settings.ai_provider == "openai" and settings.openai_api_key:
        return OpenAIProvider(settings.openai_api_key)
    if settings.ai_provider == "gemini" and settings.gemini_api_key:
        return GeminiProvider(settings.gemini_api_key)
    if settings.ai_provider == "opencode":
        return OpenCodeProvider(
            settings.opencode_endpoint,
            settings.opencode_provider_id,
            settings.opencode_model_id,
            settings.opencode_vision_model_id,
            settings.opencode_agent,
        )
    return MockProvider()
