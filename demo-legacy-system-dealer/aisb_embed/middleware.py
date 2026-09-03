"""
HTMLレスポンスの </body> 直前に埋め込みサイドバーの <script> タグ群を
差し込む Starlette ミドルウェア。

main.py 側のルート関数・テンプレートは一切変更しない(=レガシー画面のコードは
無改造のまま)。有効/無効は config.is_enabled() を毎リクエスト参照するだけなので、
サーバー再起動なしで /aisb-embed/admin からトグルできる。

サイドバー本体はビルドツールを持たない複数ファイル構成(chrome-extension側の
shared/+modules/panel-*.js 構造をそのまま移植したもの)なので、1本の<script>では
なく依存順(shared → 各panel → bootstrap)に並んだ複数の<script defer>を注入する。
defer属性により、複数<script>間の実行順序はdocument順のまま保たれる。

サブパス公開対応: 同一プロセスがサブドメイン直下(例: aisync-dealer.0101.click/)と
Caddyのstrip_prefix経由サブパス(例: aisync.0101.click/dealer/…)の両方から
リバースプロキシされうるため、注入するURLは起動時固定ではなくリクエスト単位で
Caddyが付与する X-Forwarded-Prefix ヘッダーから都度組み立てる(ヘッダー無し=""
なら従来と完全に同一の出力になる)。
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import Response

from . import config

# 依存順: shared(config-base→dom-base→api-base→ui-base→auto-input-engine) →
# modules/panel-*.js(順不同、window.AISB.panelsへの登録のみ) → modules/bootstrap.js(最後)。
# chrome-extension/manifest.json の content_scripts.js 配列と同じ並びを維持すること。
_SCRIPT_FILES = [
    "shared/config-base.js",
    "shared/dom-base.js",
    "shared/api-base.js",
    "shared/ui-base.js",
    "shared/auto-input-engine.js",
    "modules/panel-chat.js",
    "modules/panel-legacy.js",
    "modules/panel-nlsql.js",
    "modules/panel-customers.js",
    "modules/panel-ocr.js",
    "modules/panel-search.js",
    "modules/panel-analytics.js",
    "modules/panel-workflows.js",
    "modules/panel-notifications.js",
    "modules/panel-inventory.js",
    "modules/panel-purchase.js",
    "modules/panel-profit.js",
    "modules/panel-arap.js",
    "modules/panel-alerts.js",
    "modules/panel-recommend.js",
    "modules/panel-web-search.js",
    "modules/panel-assistant.js",
    "modules/panel-conv-input.js",
    "modules/panel-admin.js",
    "modules/bootstrap.js",
]


def _build_injection(prefix: str) -> str:
    script_tags = "\n".join(f'<script src="{prefix}/aisb-embed/static/{f}" defer></script>' for f in _SCRIPT_FILES)
    # config-base.js側(LEGACY_ORIGIN組み立て)・ui-base.js側(sidebar.css読み込み)が
    # 参照する、このページが公開されている外部パスプレフィックス。
    return f'<script>window.AISB_BASE_PATH = {prefix!r};</script>\n{script_tags}'


class AisbEmbedMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request, call_next):
        response = await call_next(request)

        if not config.is_enabled():
            return response
        # 自分自身の管理画面/静的ファイル/APIには注入しない(無限ループや二重注入を防ぐ)。
        # Caddyがstrip_prefixした後にこのプロセスへ届くパスなので、プレフィックスは
        # 含まれず従来通りの判定でよい。
        if request.url.path.startswith("/aisb-embed"):
            return response
        content_type = response.headers.get("content-type", "")
        if "text/html" not in content_type:
            return response

        body = b"".join([chunk async for chunk in response.body_iterator])
        try:
            html = body.decode("utf-8")
        except UnicodeDecodeError:
            # HTMLとして解釈できないなら手を加えず素通しする
            return Response(
                content=body,
                status_code=response.status_code,
                headers=dict(response.headers),
                media_type=response.media_type,
            )

        if "</body>" in html:
            prefix = request.headers.get("x-forwarded-prefix", "")
            html = html.replace("</body>", f"{_build_injection(prefix)}\n</body>", 1)

        new_body = html.encode("utf-8")
        headers = dict(response.headers)
        headers["content-length"] = str(len(new_body))
        return Response(
            content=new_body,
            status_code=response.status_code,
            headers=headers,
            media_type=response.media_type,
        )
