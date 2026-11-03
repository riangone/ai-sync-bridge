"""既存の読み取り専用 HTTP 一覧API(GET {base_url}/api/{entity}/list)を全件取得する。
最も侵襲の少ない接続方式: レガシー側は既存の一覧APIを提供するだけでよい。"""
from __future__ import annotations

import httpx

from app.bridge.connectors.base import Connector, FetchResult
from app.bridge.models import EntitySpec


class HttpListConnector(Connector):
    type_name = "http_list"

    async def fetch(self, entity: EntitySpec, cursor: dict | None) -> FetchResult:
        base = self.config["base_url"].rstrip("/")
        path = entity.options.get("path", f"/api/{entity.name}/list")
        limit = int(self.config.get("limit", 10000))
        async with httpx.AsyncClient(timeout=float(self.config.get("timeout", 30))) as client:
            resp = await client.get(base + path, params={"limit": limit})
            resp.raise_for_status()
            data = resp.json()
        rows = data.get("rows", data) if isinstance(data, dict) else data
        if isinstance(data, dict) and isinstance(data.get("count"), int) and data["count"] > len(rows):
            # 上限で切れた一覧を snapshot 扱いすると、取りこぼした行を「削除」と誤判定する
            raise RuntimeError(f"{entity.name}: 一覧が limit={limit} で打ち切られています(count={data['count']})")
        return FetchResult(rows=list(rows), cursor=None, snapshot=True)

    def describe(self) -> dict:
        return {**super().describe(), "base_url": self.config.get("base_url")}
