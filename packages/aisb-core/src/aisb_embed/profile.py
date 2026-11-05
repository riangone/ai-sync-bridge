"""
デモ(=導入先レガシーシステム)ごとの差分定義。

コア(このパッケージ)は業種非依存の共通サイドバーだけを持ち、業種ごとの違いは
すべて導入先の `aisb_profile/` ディレクトリに閉じ込める:

    aisb_profile/
      profile.json   … 表示名・追加パネル等のメタ情報(任意)
      state.json     … 埋め込み有効/無効のトグル状態(自動生成・gitignore)
      static/        … コアの static/ と同じ相対パスに置いたファイルが優先される
                       (例: shared/config-base.js, shared/demo-scenarios.js)

コアのソースを導入先ごとにコピー・改変することは禁止(過去に5コピーが分岐した反省)。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class EmbedProfile:
    profile_dir: Path
    # 管理画面の説明文に出す導入先システム名
    system_label: str = "レガシーERP"
    # コアの既定スクリプト列に加えて注入するモジュール(例: modules/panel-valuation.js)
    extra_modules: tuple[str, ...] = field(default_factory=tuple)
    # AI パネルの上部に常時表示する注意書き。{"text", "link_label", "link_url"}。未指定なら表示しない
    ai_notice: dict[str, str] | None = None
    # AI パネルを注入しないパス(例: パネルの利用者がまだ決まらないロール選択画面)
    embed_exclude_paths: tuple[str, ...] = field(default_factory=tuple)

    @property
    def static_dir(self) -> Path:
        return self.profile_dir / "static"

    @property
    def state_file(self) -> Path:
        return self.profile_dir / "state.json"

    @classmethod
    def load(cls, profile_dir: Path | str | None = None) -> "EmbedProfile":
        pdir = Path(profile_dir) if profile_dir else Path.cwd() / "aisb_profile"
        meta: dict = {}
        pj = pdir / "profile.json"
        if pj.exists():
            meta = json.loads(pj.read_text(encoding="utf-8"))
        return cls(
            profile_dir=pdir,
            system_label=meta.get("system_label", cls.system_label),
            extra_modules=tuple(meta.get("extra_modules", [])),
            ai_notice=meta.get("ai_notice"),
            embed_exclude_paths=tuple(meta.get("embed_exclude_paths", [])),
        )
