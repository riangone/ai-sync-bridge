"""
レガシー読み取り専用API 共有クライアント
==========================================
demo-legacy-system が公開する GET /api/{entity}/list (6.1章: レガシー側は
AI-Sync Bridgeの存在を一切知らない、完全な副次的読み取り専用エンドポイント)から
実データを取得する処理は nlsql_service と cross_analysis_service の両方で
必要になるため、ここに一本化した(元は nlsql_service._fetch_rows に閉じていた)。
レガシー側への変更・追加エンドポイント要求は一切ない。
"""
import httpx

from app.config import Settings

MAX_ROWS_FETCHED = 500  # プロンプト肥大化/レイテンシ防止の上限(nlsql_service由来の値を流用)


async def fetch_rows(settings: Settings, entity: str, limit: int = MAX_ROWS_FETCHED) -> tuple[list[dict], str]:
    """指定エンティティの全行(labelとrows)を返す。存在しないentityはhttpx.HTTPStatusError(404)。"""
    url = f"{settings.legacy_base_url}/api/{entity}/list"
    async with httpx.AsyncClient(timeout=10) as client:
        resp = await client.get(url, params={"limit": limit})
        resp.raise_for_status()
        data = resp.json()
    return data.get("rows", []), data.get("label", entity)
