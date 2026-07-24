"""
マルチAIプロバイダ抽象化層 (仕様 8.2: AiHttpClient)
OpenCode CLI / OpenAI / Gemini / Mock を単一インターフェースで吸収する。
呼び出し側 (chat_service, search_service) はプロバイダの違いを意識しない。
"""
from abc import ABC, abstractmethod
import httpx
from app.config import Settings


class AiProvider(ABC):
    name: str

    @abstractmethod
    async def complete(self, prompt: str, history: list[dict] | None = None) -> str: ...

    @abstractmethod
    async def embed(self, text: str) -> list[float]: ...


class MockProvider(AiProvider):
    """デモモード/APIキー未設定時のフォールバック。決定論的な擬似応答を返す。"""
    name = "mock"

    async def complete(self, prompt: str, history: list[dict] | None = None) -> str:
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

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, prompt: str, history: list[dict] | None = None) -> str:
        messages = (history or []) + [{"role": "user", "content": prompt}]
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    "https://api.openai.com/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.api_key}"},
                    json={"model": "gpt-4o-mini", "messages": messages},
                )
                resp.raise_for_status()
                return resp.json()["choices"][0]["message"]["content"]
            except Exception as exc:  # フォールバック
                return f"[openai-error-fallback] {exc}"

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

    def __init__(self, api_key: str):
        self.api_key = api_key

    async def complete(self, prompt: str, history: list[dict] | None = None) -> str:
        url = (
            "https://generativelanguage.googleapis.com/v1beta/models/"
            f"gemini-1.5-flash:generateContent?key={self.api_key}"
        )
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(url, json={"contents": [{"parts": [{"text": prompt}]}]})
                resp.raise_for_status()
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"]
            except Exception as exc:
                return f"[gemini-error-fallback] {exc}"

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

    def __init__(self, endpoint: str, provider_id: str, model_id: str):
        self.endpoint = endpoint.rstrip("/")
        self.provider_id = provider_id
        self.model_id = model_id

    def _build_prompt(self, prompt: str, history: list[dict] | None) -> str:
        if not history:
            return prompt
        lines = [f"{h.get('role', 'user')}: {h.get('content', '')}" for h in history]
        lines.append(f"user: {prompt}")
        return "これまでの会話:\n" + "\n".join(lines)

    async def complete(self, prompt: str, history: list[dict] | None = None) -> str:
        full_prompt = self._build_prompt(prompt, history)
        try:
            async with httpx.AsyncClient(timeout=120) as client:
                session_resp = await client.post(f"{self.endpoint}/session", json={})
                session_resp.raise_for_status()
                session_id = session_resp.json()["id"]

                msg_resp = await client.post(
                    f"{self.endpoint}/session/{session_id}/message",
                    json={
                        "model": {"providerID": self.provider_id, "modelID": self.model_id},
                        "parts": [{"type": "text", "text": full_prompt}],
                    },
                )
                msg_resp.raise_for_status()
                parts = msg_resp.json().get("parts", [])
                text = "".join(p.get("text", "") for p in parts if p.get("type") == "text")
                return text or "[opencode-empty-response]"
        except Exception as exc:
            return f"[opencode-error-fallback] {exc}"

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
        )
    return MockProvider()
