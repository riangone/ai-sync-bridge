"""
aisb_embed — Chrome拡張機能(AI-Sync Bridge)と同じサイドバー機能を、拡張なしで
レガシーシステム自身に直接埋め込むための自己完結アドオン(aisb-core パッケージ)。

導入先(レガシー側)の変更は main.py の2行のみ:
    import aisb_embed
    aisb_embed.mount(app, profile_dir=Path(__file__).parent / "aisb_profile")

  - サイドバー注入はテンプレート編集ではなく HTTP ミドルウェアが </body> 直前に
    <script defer> 群を差し込む方式(middleware.py)。
  - 有効/無効は /aisb-embed/admin から再起動なしで切り替え可能(config.py)。
  - 業種差分は導入先の aisb_profile/ に閉じ込める(profile.py)。静的ファイルは
    aisb_profile/static/ → コア static/ の順に解決するオーバーレイ方式。
    コアのソースを導入先にコピーして改変しないこと。
"""
from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from . import config, routes
from .middleware import AisbEmbedMiddleware
from .profile import EmbedProfile

_CORE_STATIC_DIR = Path(__file__).parent / "static"

__all__ = ["mount", "EmbedProfile"]


def _layered_static(profile: EmbedProfile) -> StaticFiles:
    static = StaticFiles(directory=str(_CORE_STATIC_DIR))
    # StaticFiles.lookup_path は all_directories を先頭から探索する
    # → 導入先の override を先に置くことでコアのファイルを差し替えられる。
    if profile.static_dir.is_dir():
        static.all_directories = [str(profile.static_dir), *static.all_directories]
    return static


def mount(app: FastAPI, profile_dir: Path | str | None = None) -> EmbedProfile:
    profile = EmbedProfile.load(profile_dir)
    config.set_state_file(profile.state_file)
    routes.SYSTEM_LABEL = profile.system_label
    app.add_middleware(AisbEmbedMiddleware, profile=profile)
    app.include_router(routes.router)
    app.mount("/aisb-embed/static", _layered_static(profile), name="aisb_embed_static")
    return profile
