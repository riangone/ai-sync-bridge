"""
Search Service (Scoped)
仕様8.3の3層ベクトル検索: 実体は VectorIndexManager(Singleton) に委譲する。
このクラス自体はリクエスト毎に生成されて構わないが、埋め込みキャッシュ/インデックスは
必ず Singleton 側に保持し、ここでは持たない（DIライフサイクルの原則）。
"""
from app.services.ai_client import AiProvider
from app.services.demo_data import DemoDataStore
from app.services.vector_index import VectorIndexManager


class SearchService:
    def __init__(self, ai: AiProvider, store: DemoDataStore, index: VectorIndexManager):
        self.ai = ai
        self.store = store
        self.index = index

    async def search(self, query: str, top_k: int = 5) -> dict:
        # 差分同期: 更新されていない顧客は再埋め込みしない
        await self.index.sync(self.store, self.ai)

        query_vec = await self.ai.embed(query)
        # キーワード一致ボーナスで順位が入れ替わる余地を残すため、top_k より広めに候補を取得する
        pool_size = min(max(top_k * 5, 20), max(self.index.size(), 1))
        hits = await self.index.search(query_vec, pool_size)

        by_id = {c["id"]: c for c in self.store.list_customers()}
        scored = []
        for cid, score in hits:
            c = by_id.get(cid)
            if not c:
                continue
            haystack = f"{c['name']} {c.get('company') or ''} {c.get('notes') or ''}"
            if query.lower() in haystack.lower():
                score += 0.5
            scored.append((score, c))

        scored.sort(key=lambda x: x[0], reverse=True)
        results = [
            {
                "id": c["id"],
                "type": "customer",
                "title": c["name"],
                "snippet": c.get("company") or c.get("notes") or "",
                "score": round(score, 4),
            }
            for score, c in scored[:top_k]
        ]
        return {"query": query, "backend": self.index.backend_name, "results": results}
