#!/usr/bin/env python
"""
ブリッジの実測スクリプト。仕様書の「実測値」はこの出力から転記する。

    cd ai-api-server && .venv/bin/python scripts/bench_bridge.py --docs 10000
    (最大メモリを規模ごとに分けて測るため、規模ごとに別プロセスで実行する)

データは合成 CSV、埋め込みは MockProvider の外部通信なしの簡易ハッシュ。本番の埋め込み API を
使う場合の同期時間はこの値に含まれない。検索語は文書と同じ語彙から作るので、精度の評価には使えない。
"""
import argparse
import asyncio
import json
import os
import resource
import statistics
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.bridge.acl import Principal  # noqa: E402
from app.bridge.runtime import BridgeRuntime  # noqa: E402
from app.services.ai_client import MockProvider  # noqa: E402

DEPTS = ["営業部", "経理部", "人事部", "製造部", "購買部"]
WORDS = ["配管", "軸受", "制御盤", "保守", "点検", "納期", "請求", "見積", "在庫", "検収", "図面", "仕様"]
QUERIES = 60


class CountingEmbed:
    def __init__(self):
        self.provider = MockProvider()
        self.calls = 0

    async def __call__(self, text):
        self.calls += 1
        return await self.provider.embed(text)


def write_csv(path, docs, changed=None):
    with open(path, "w", encoding="cp932", newline="") as f:
        f.write("id,name,dept,notes\n")
        for i in range(docs):
            a, b = WORDS[i % len(WORDS)], WORDS[(i * 7 + 3) % len(WORDS)]
            notes = "変更あり" if i == changed else f"{a}と{b}に関する記録 {i}"
            f.write(f"R{i},案件{i},{DEPTS[i % len(DEPTS)]},{notes}\n")


def profile(tmp):
    return {
        "store": {"path": os.path.join(tmp, "bridge.db")},
        "sources": [{"name": "files", "type": "file", "config": {"base_dir": tmp}, "entities": [{
            "name": "Rec", "pk": "id", "title": "name", "text": ["name", "dept", "notes"],
            "acl": {"tenant": "t1", "roles": ["all"]},
            "options": {"path": "rows.csv"},
        }]}],
    }


def build(tmp, embed, backend):
    return BridgeRuntime(profile(tmp), embed=embed, embedder_id="ngram-hash-64",
                         default_store_path=os.path.join(tmp, "bridge.db"), vector_backend=backend)


async def timed_sync(rt):
    t = time.perf_counter()
    await rt.sync("bench")
    return time.perf_counter() - t


async def run(docs, backend):
    principal = Principal(user_id="bench", tenant="t1", roles=("all",))
    with tempfile.TemporaryDirectory() as tmp:
        csv_path = os.path.join(tmp, "rows.csv")
        write_csv(csv_path, docs)
        embed = CountingEmbed()
        rt = build(tmp, embed, backend)
        first = await timed_sync(rt)
        first_calls = embed.calls

        embed.calls = 0
        await timed_sync(rt)
        unchanged_calls = embed.calls

        write_csv(csv_path, docs, changed=docs // 2)
        embed.calls = 0
        one_row = await timed_sync(rt)
        one_row_calls = embed.calls

        embed.calls = 0
        t = time.perf_counter()
        rt = build(tmp, embed, backend)
        restart = time.perf_counter() - t
        restart_calls = embed.calls

        latencies = []
        for i in range(QUERIES):
            q = f"{WORDS[i % len(WORDS)]} {DEPTS[i % len(DEPTS)]}"
            t = time.perf_counter()
            await rt.search(principal, q, top_k=5)
            latencies.append((time.perf_counter() - t) * 1000)
        latencies.sort()

        return {
            "docs": docs,
            "requested_backend": backend,
            "actual_backend": rt.retriever.backend_name,
            "first_sync_sec": round(first, 2),
            "first_sync_embeds": first_calls,
            "unchanged_sync_embeds": unchanged_calls,
            "one_row_sync_sec": round(one_row, 2),
            "one_row_sync_embeds": one_row_calls,
            "restart_load_sec": round(restart, 2),
            "restart_embeds": restart_calls,
            "search_p50_ms": round(statistics.median(latencies), 1),
            "search_p95_ms": round(latencies[int(QUERIES * 0.95) - 1], 1),
            "max_rss_mb": round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024),
        }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--docs", type=int, required=True)
    ap.add_argument("--backend", default="brute-force", choices=["sqlite-vec", "ann", "brute-force"])
    args = ap.parse_args()
    print(json.dumps(asyncio.run(run(args.docs, args.backend)), ensure_ascii=False))
