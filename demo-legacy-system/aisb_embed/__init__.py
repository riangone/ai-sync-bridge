"""
aisb_embed — Chrome拡張機能(AI-Sync Bridge)と同じサイドバー機能を、拡張なしで
レガシーシステム自身に直接埋め込むための自己完結アドオン。

設計方針(「レガシー側のコードを極力汚さない」「簡単にON/OFFできる」の両立):

  - レガシー側(main.py/templates/data.py)への変更は、main.py 冒頭の
        import aisb_embed
        aisb_embed.mount(app)
    の2行のみ。ルート関数・テンプレートは1文字も変更しない。
  - サイドバーの注入はテンプレート編集ではなく、HTTPミドルウェアが
    レスポンスHTMLの </body> 直前に <script defer> タグ群を差し込む方式
    (middleware.py)。したがって新規画面を追加してもこの2行以外
    何も意識する必要がない。
  - 有効/無効は config.py が管理し、/aisb-embed/admin から
    サーバー再起動なしでいつでも切り替えられる。無効化すると
    ミドルウェアは何もせず素通しになり、レガシー画面は完全に
    素のHTMLへ戻る(注入されたJS/CSSも一切残らない)。
  - サイドバー本体(static/shared/*.js, static/modules/panel-*.js,
    static/sidebar.css)は chrome-extension/shared/+modules/ の移植版。
    panel-*.js は環境依存コードを一切含まないため、拡張側と完全に同一内容。
    shared/config-base.js・shared/ui-base.js・modules/bootstrap.js のみ
    chrome.storage.local → localStorage 等の環境依存部分を差し替えている。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .middleware import AisbEmbedMiddleware
from .routes import router

_STATIC_DIR = Path(__file__).parent / "static"


def mount(app: FastAPI) -> None:
    app.add_middleware(AisbEmbedMiddleware)
    app.include_router(router)
    app.mount("/aisb-embed/static", StaticFiles(directory=str(_STATIC_DIR)), name="aisb_embed_static")
