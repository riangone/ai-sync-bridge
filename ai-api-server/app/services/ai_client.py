"""
マルチAIプロバイダ抽象化層 (仕様 8.2: AiHttpClient)
OpenCode CLI / antigravity CLI / OpenAI / Gemini / Mock を単一インターフェースで吸収する。
呼び出し側 (chat_service, search_service) はプロバイダの違いを意識しない。
"""
import asyncio
import base64
import contextlib
import json
import os
import signal
import time
from abc import ABC, abstractmethod
from collections import deque
from pathlib import Path
import httpx
from app.config import Settings
from app.services.ai_guard import GUARDRAIL_SYSTEM_PROMPT, build_tool_flags, redact_output
from app.services.rate_limit import SlidingWindowLimiter, current_client


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
        # httpx のタイムアウト等は str() が空になるので、原因が消えないよう repr に倒す
        super().__init__(f"[{provider}] AIプロバイダ呼び出しに失敗しました: {str(original) or repr(original)}")


class AIRateLimitError(AIProviderError):
    """送信元ごとの回数上限に達した。縮退応答を持つ呼び出し側では通常の AI 失敗と同じ扱いになる。"""


def _prompt_with_history(prompt: str, history: list[dict] | None) -> str:
    """CLI 系プロバイダはセッションを使い捨てるため、履歴をプロンプト先頭に埋め込む。"""
    if not history:
        return prompt
    lines = [f"{h.get('role', 'user')}: {h.get('content', '')}" for h in history]
    lines.append(f"user: {prompt}")
    return "これまでの会話:\n" + "\n".join(lines)


class AiProvider(ABC):
    name: str
    # 埋め込みベクトルの互換性ID。これが変わるとブリッジは全文書を再埋め込みする。
    embedder_id: str = "unknown"
    supports_vision: bool = False
    # complete(tools={"websearch": True}) で実際にWeb検索できるか。
    supports_web_search: bool = False

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


_GEMINI_BASE = "https://generativelanguage.googleapis.com/v1beta"


class GeminiProvider(AiProvider):
    name = "gemini"
    # 埋め込みは実モデル。ID を擬似埋め込み(ngram-hash)と分けることで、切り替えた時点で
    # 全文書が再埋め込み対象になる(sync_engine が embedder_id の不一致を見る)。
    embedder_id = "gemini:gemini-embedding-2@768"
    _EMBED_MODEL = "gemini-embedding-2"
    _EMBED_DIM = 768

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

    async def embed_query(self, text: str) -> list[float]:
        return await self.embed(text, kind="query")

    async def embed(self, text: str, kind: str = "doc") -> list[float]:
        """埋め込みの失敗を擬似埋め込みで隠さない(fail loud)。

        kind: "doc"(文書の索引) or "query"(検索語)。Gemini Embedding 2 は task_type を
        受け付けないため、入力の体裁で非対称検索の向きを伝える。

        以前は MockProvider の n-gram ハッシュに黙って委譲していたため、埋め込みモデルを
        変えた直後もエラーが出ずに「静かに精度が落ちる」だけだった。gemini への委譲中は
        AIProviderError が同期の失敗として上がる(sync_engine は該当エンティティを失敗扱いし、
        既存の文書とベクトルは書き換えない)。
        """
        # Gemini Embedding 2 は task_type を受け付けず、非対称検索では入力の体裁で向きを示す:
        #   query:    "task: search result | query: {本文}"
        #   document: "title: {タイトル} | text: {本文}"
        # 呼び出し元(ベクトル索引の既存の約束)は "タイトル 本文" を連結して渡すので、
        # 文書側は title: none にまとめる。全件で同じ接頭辞にならないよう本文はそのまま残す。
        if kind == "query":
            payload_text = f"task: search result | query: {text}"
        else:
            payload_text = f"title: none | text: {text}"
        async with httpx.AsyncClient(timeout=30) as client:
            try:
                resp = await client.post(
                    f"{_GEMINI_BASE}/models/{self._EMBED_MODEL}:embedContent",
                    headers={"x-goog-api-key": self.api_key},
                    json={"content": {"parts": [{"text": payload_text}]},
                          "output_dimensionality": self._EMBED_DIM},
                )
                resp.raise_for_status()
                values = resp.json()["embedding"]["values"]
            except Exception as exc:
                raise AIProviderError(self.name, exc) from exc
        if not values:
            raise AIProviderError(self.name, RuntimeError("空の埋め込みが返されました"))
        # 3072 次元以外は自動正規化されるが、次元を自前で選ぶ可能性に備えて必ず正規化する
        norm = sum(v * v for v in values) ** 0.5 or 1.0
        return [v / norm for v in values]


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
    supports_web_search = True

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

    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str:
        """tools: {"websearch": true} のように明示指定すると、そのツールだけを有効化する。
        ai_guard.ALLOWED_TOOLS 以外(bash/read/webfetch等)は要求されても常に無効。
        未指定時は全ツール無効(旧実装は「未指定=全ツール利用可」で、チャットから実サーバーの
        bash が実行された。2026-10-26 インシデント)。"""
        full_prompt = _prompt_with_history(prompt, history)
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


class AntigravityProvider(AiProvider):
    """ローカルの antigravity CLI をヘッドレス実行するプロバイダ。

    CLI はファイル読取やシェルを持つエージェントで、既定エージェントは ~/.gemini 側の allow
    ルール(cat 等)をヘッドレスでも適用する。公開デモの入力をそのまま渡すと 2026-10-26 の
    リモートコマンド実行が再発するため(canary で実地確認)、次を必ず重ねる:
      1. ツール無しの専用エージェントを --agent で常に明示する(本命)。
         エージェント定義が見つからなければ CLI はエラー終了する(fail closed)。
      2. ストリームで許可外ツールの実行を検知したらプロセスを止めて応答を破棄する。
      3. --settings で永続 allow ルールを無効化する。ただし command を塞ぐだけで read_file 等は
         止まらないため、これ単体を防御として頼らないこと。
      4. 環境変数は最小限に絞り、プロンプトは stdin で渡す(ps に業務データを出さない)。
    --dangerously-skip-permissions は絶対に付けないこと。

    画像は stream-json 入力が受け付けず(text のみ)、ファイル読取ツールを許可するしか方法が
    無いため vision は非対応とする。
    """
    name = "antigravity"
    embedder_id = "ngram-hash-64"  # embed() は MockProvider へ委譲している
    supports_web_search = True

    _AGENT = "aisync-demo"
    _WEB_AGENT = "aisync-demo-web"
    _WEB_TOOL = "search_web"
    _SESSION_SETTINGS = json.dumps({
        "permissions": {"allow": [], "deny": ["command(*)"]},
        "allowNonWorkspaceAccess": False,
    })
    _ENV_KEYS = ("HOME", "USER", "PATH", "LANG")
    _STREAM_LINE_LIMIT = 8 * 1024 * 1024

    def __init__(self, binary: str, model: str, workdir: str, timeout: float = 90,
                 max_concurrency: int = 2, max_calls_per_hour: int = 120):
        self.binary = binary
        self.model = model
        self.workdir = workdir
        self.timeout = timeout
        self.max_calls_per_hour = max_calls_per_hour
        self._semaphore = asyncio.Semaphore(max_concurrency)
        self._recent_calls: deque[float] = deque()
        self._write_agents()

    def _write_agents(self) -> None:
        """エージェント定義を生成する。リポジトリ外に置くのは CLAUDE.md 等を読ませないため。"""
        agents_dir = Path(self.workdir) / ".agents" / "agents"
        agents_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
        web_note = (
            "\n例外: Web検索(search_web)だけは使えます。指示文の websearch は search_web を指します。\n"
        )
        for agent, tools, extra in (
            (self._AGENT, "[]", ""),
            (self._WEB_AGENT, f"[{self._WEB_TOOL}]", web_note),
        ):
            text = (
                f"---\nname: {agent}\n"
                "description: AI-Sync demo assistant\n"
                "mainAgent: true\nsubagent: false\nexcludeDefaultComponents: true\n"
                f"inheritMcp: false\ntools: {tools}\nskills: []\nrules: []\nagents: []\n"
                f"---\n# AI-Sync Bridge\n{GUARDRAIL_SYSTEM_PROMPT}{extra}"
            )
            # 複数インスタンスが同時に起動しても読み手が書きかけを見ないよう一時ファイル経由で置く。
            tmp = agents_dir / f".{agent}.{os.getpid()}.tmp"
            tmp.write_text(text, encoding="utf-8")
            os.replace(tmp, agents_dir / f"{agent}.md")

    def _reserve_call(self) -> None:
        """公開デモから利用者の AI クレジットを使い切られないよう、呼び出し回数に上限を設ける。"""
        now = time.monotonic()
        while self._recent_calls and now - self._recent_calls[0] > 3600:
            self._recent_calls.popleft()
        if len(self._recent_calls) >= self.max_calls_per_hour:
            raise AIProviderError(self.name, "1時間あたりの呼び出し上限に達しました")
        self._recent_calls.append(now)

    async def _read_result(self, stdout: asyncio.StreamReader, allowed_tools: frozenset[str]) -> dict:
        """イベントを順に読み、許可外ツールを見つけた時点で打ち切る。"""
        result: dict = {}
        async for line in stdout:
            try:
                event = json.loads(line)
            except ValueError:
                continue
            if event.get("event") == "result":
                result = event.get("result") or {}
                continue
            step = event.get("step_update") or {}
            if step.get("step_type") == "tool" and step.get("tool_name") not in allowed_tools:
                raise AIProviderError(
                    self.name, f"許可されていないツール実行を検知したため応答を破棄しました: {step.get('tool_name')}"
                )
        return result

    async def _run(self, prompt: str, allow_web: bool) -> str:
        message = json.dumps({"event": "user", "message": {"role": "user", "content": prompt}})
        proc = await asyncio.create_subprocess_exec(
            self.binary,
            "--print", "",
            "--agent", self._WEB_AGENT if allow_web else self._AGENT,
            "--model", self.model,
            "--disable-slash-commands",
            "--sandbox",
            "--settings", self._SESSION_SETTINGS,
            "--print-timeout", f"{int(self.timeout)}s",
            "--input-format", "stream-json",
            "--output-format", "stream-json",
            cwd=self.workdir,
            env={k: os.environ[k] for k in self._ENV_KEYS if k in os.environ},
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            limit=self._STREAM_LINE_LIMIT,
            start_new_session=True,
        )
        allowed_tools = frozenset({self._WEB_TOOL}) if allow_web else frozenset()

        async def communicate() -> tuple[dict, bytes]:
            proc.stdin.write(message.encode("utf-8") + b"\n")
            await proc.stdin.drain()
            proc.stdin.close()
            stderr_task = asyncio.create_task(proc.stderr.read())
            try:
                result = await self._read_result(proc.stdout, allowed_tools)
                await proc.wait()
                return result, await stderr_task
            finally:
                stderr_task.cancel()

        try:
            result, stderr = await asyncio.wait_for(communicate(), timeout=self.timeout + 5)
        except asyncio.TimeoutError as exc:
            raise AIProviderError(self.name, f"{self.timeout:.0f}秒以内に応答がありませんでした") from exc
        finally:
            # 打ち切り時に CLI の子プロセスごと確実に止める(正常終了後は既に居ない)。
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError):
                    os.killpg(proc.pid, signal.SIGKILL)
                await proc.wait()

        # 許可された操作だけを通すため、CLI に拒否された操作が1つでもあれば応答ごと破棄する。
        if result.get("denied_actions"):
            actions = [a.get("action") for a in result["denied_actions"]]
            raise AIProviderError(self.name, f"許可されていない操作の要求を検知したため応答を破棄しました: {actions}")
        response = result.get("response") or ""
        if proc.returncode != 0 or result.get("status") != "SUCCESS" or not response.strip():
            # 上流のエラー(クレジット切れ等)の原因が空にならないよう stderr まで見る。
            detail = result.get("error") or stderr.decode("utf-8", "replace").strip() or f"exit={proc.returncode}"
            raise AIProviderError(self.name, redact_output(detail)[:500])
        return redact_output(response)

    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str:
        """tools に {"websearch": true} を明示した場合のみ Web 検索を許可する。他は常に無効。"""
        self._reserve_call()
        allow_web = build_tool_flags(tools)["websearch"]
        try:
            async with self._semaphore:
                return await self._run(_prompt_with_history(prompt, history), allow_web)
        except AIProviderError:
            raise
        except Exception as exc:
            raise AIProviderError(self.name, exc) from exc

    async def embed(self, text: str) -> list[float]:
        # CLI は埋め込みを公開していないため n-gram 擬似埋め込みに委譲する。opencode と同じ
        # embedder_id なので、プロバイダを切り替えても再埋め込みは発生しない。
        return await MockProvider().embed(text)


class PerClientLimitedProvider(AiProvider):
    """LLM を呼ぶ前に送信元ごとの回数を数えるラッパー。送信元のない呼び出しは数えない。
    埋め込みは数えない(CLI 系はローカル処理で、呼び出し回数が LLM 消費に対応しないため)。"""

    def __init__(self, inner: AiProvider, per_hour: int):
        self.inner = inner
        self._limiter = SlidingWindowLimiter(per_hour, 3600)

    name = property(lambda self: self.inner.name)
    embedder_id = property(lambda self: self.inner.embedder_id)
    supports_vision = property(lambda self: self.inner.supports_vision)
    supports_web_search = property(lambda self: self.inner.supports_web_search)

    def __getattr__(self, item):
        return getattr(self.inner, item)

    def _check(self) -> None:
        client = current_client.get()
        if client is not None and not self._limiter.allow(client):
            raise AIRateLimitError(self.inner.name, f"送信元ごとの上限に達しました: {client}")

    async def complete(self, prompt: str, history: list[dict] | None = None, tools: dict[str, bool] | None = None) -> str:
        self._check()
        return await self.inner.complete(prompt, history, tools)

    async def complete_vision(self, prompt: str, image_bytes: bytes, mime: str) -> str:
        self._check()
        return await self.inner.complete_vision(prompt, image_bytes, mime)

    async def embed(self, text: str) -> list[float]:
        return await self.inner.embed(text)


def build_ai_provider(settings: Settings) -> AiProvider:
    """設定に応じてプロバイダを選択。キー未設定/接続失敗は呼び出し側でMockにフォールバック可。"""
    if settings.ai_provider == "antigravity":
        return AntigravityProvider(
            settings.antigravity_binary,
            settings.antigravity_model,
            settings.antigravity_workdir,
            settings.antigravity_timeout,
            settings.antigravity_max_concurrency,
            settings.antigravity_max_calls_per_hour,
        )
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
