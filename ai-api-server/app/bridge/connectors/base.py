"""
Connector 抽象: レガシーデータソースからの「読み取り専用」差分取得。

fetch() は FetchResult を返す:
  - snapshot=True  : rows が全件。SyncEngine は rows に無い既存文書を削除扱いにする。
  - snapshot=False : rows は前回カーソル以降の変更分のみ(deleted に削除pkを入れてもよい)。
  - cursor         : 次回 fetch に渡される不透明な状態(BridgeStore に永続化される)。
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from app.bridge.models import EntitySpec


@dataclass
class FetchResult:
    rows: list[dict]
    cursor: dict | None
    snapshot: bool
    deleted: list[str] = field(default_factory=list)
    unchanged: bool = False  # ソース全体が未変更と判定できた(ファイル指紋一致など)


class Connector(ABC):
    type_name: str = ""

    def __init__(self, name: str, config: dict):
        self.name = name
        self.config = config

    @abstractmethod
    async def fetch(self, entity: EntitySpec, cursor: dict | None) -> FetchResult: ...

    def describe(self) -> dict:
        """管理画面/ API 用。秘密情報(接続文字列のパスワード等)を含めないこと。"""
        return {"name": self.name, "type": self.type_name}
