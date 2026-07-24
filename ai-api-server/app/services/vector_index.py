"""
Vector Index (Singleton) - 仕様8.3: 3層ベクトル検索
sqlite-vec(最速・要ネイティブ拡張) -> RandomProjectionIndex(自前ANN) -> ブルートフォース(常に確実)
の順に自動フォールバックし、出力形式 (id, score) のリストは全バックエンドで統一する。

DIライフサイクル注意点: 埋め込みキャッシュとインデックス本体はプロセス内で使い回す
Singleton でなければならない。SearchService(Scoped) が毎リクエストで作り直すと、
インデックス構築のたびに全顧客を再埋め込みすることになり検索が線形に遅くなる。
"""
from __future__ import annotations

import asyncio
import json
import math
import random
from abc import ABC, abstractmethod
from typing import Any

from app.services.ai_client import AiProvider
from app.services.demo_data import DemoDataStore


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


class VectorBackend(ABC):
    name: str

    @abstractmethod
    def index(self, id_: int, vector: list[float]) -> None: ...

    @abstractmethod
    def remove(self, id_: int) -> None: ...

    @abstractmethod
    def search(self, query: list[float], top_k: int) -> list[tuple[int, float]]: ...


class BruteForceBackend(VectorBackend):
    """常に利用可能な確実層。全件コサイン類似度スキャン。"""
    name = "brute-force"

    def __init__(self) -> None:
        self._vectors: dict[int, list[float]] = {}

    def index(self, id_: int, vector: list[float]) -> None:
        self._vectors[id_] = vector

    def remove(self, id_: int) -> None:
        self._vectors.pop(id_, None)

    def search(self, query: list[float], top_k: int) -> list[tuple[int, float]]:
        scored = [(cid, _cosine(query, v)) for cid, v in self._vectors.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


class RandomProjectionBackend(VectorBackend):
    """
    自前実装 ANN: ランダム超平面 LSH。
    n_planes 本の乱数超平面に対する内積の符号でビット署名を作り、同一/近傍バケットのみを
    候補に絞ることで全件スキャンを回避する。候補が不足する場合は精度優先で全件へフォールバックする。
    """
    name = "ann"

    def __init__(self, n_planes: int = 10, seed: int = 42) -> None:
        self.n_planes = n_planes
        self._rng = random.Random(seed)
        self._planes: list[list[float]] | None = None
        self._vectors: dict[int, list[float]] = {}
        self._sig: dict[int, str] = {}
        self._buckets: dict[str, set[int]] = {}

    def _ensure_planes(self, dim: int) -> None:
        if self._planes is not None:
            return
        self._planes = [[self._rng.gauss(0, 1) for _ in range(dim)] for _ in range(self.n_planes)]

    def _signature(self, vec: list[float]) -> str:
        return "".join(
            "1" if sum(v * p for v, p in zip(vec, plane)) >= 0 else "0"
            for plane in self._planes  # type: ignore[union-attr]
        )

    def index(self, id_: int, vector: list[float]) -> None:
        self._ensure_planes(len(vector))
        self.remove(id_)
        sig = self._signature(vector)
        self._vectors[id_] = vector
        self._sig[id_] = sig
        self._buckets.setdefault(sig, set()).add(id_)

    def remove(self, id_: int) -> None:
        old_sig = self._sig.pop(id_, None)
        self._vectors.pop(id_, None)
        if old_sig is not None:
            bucket = self._buckets.get(old_sig)
            if bucket:
                bucket.discard(id_)
                if not bucket:
                    del self._buckets[old_sig]

    def search(self, query: list[float], top_k: int) -> list[tuple[int, float]]:
        if not self._vectors:
            return []
        self._ensure_planes(len(query))
        q_sig = self._signature(query)
        candidates: set[int] = set(self._buckets.get(q_sig, set()))
        # リコール確保のためハミング距離1のバケットも候補に含める
        for i in range(len(q_sig)):
            flipped = q_sig[:i] + ("0" if q_sig[i] == "1" else "1") + q_sig[i + 1:]
            candidates |= self._buckets.get(flipped, set())
        if len(candidates) < top_k:
            candidates = set(self._vectors.keys())
        scored = [(cid, _cosine(query, self._vectors[cid])) for cid in candidates]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:top_k]


class SqliteVecBackend(VectorBackend):
    """
    最速層: sqlite-vec 拡張(vec0仮想テーブル)によるベクトル検索。
    パッケージ未インストール/拡張ロード失敗時は __init__ で例外を送出し、
    呼び出し元(build_vector_backend)が ann 層へフォールバックする。
    """
    name = "sqlite-vec"

    def __init__(self) -> None:
        import sqlite3

        import sqlite_vec  # 未インストールなら ImportError -> 上位でフォールバック

        self._conn = sqlite3.connect(":memory:", check_same_thread=False)
        self._conn.enable_load_extension(True)
        sqlite_vec.load(self._conn)
        self._conn.enable_load_extension(False)
        self._dim: int | None = None
        self._ids: set[int] = set()

    def _ensure_table(self, dim: int) -> None:
        if self._dim is not None:
            return
        self._dim = dim
        self._conn.execute(f"CREATE VIRTUAL TABLE vec_items USING vec0(embedding float[{dim}])")

    def index(self, id_: int, vector: list[float]) -> None:
        self._ensure_table(len(vector))
        if len(vector) != self._dim:
            raise ValueError(f"embedding dimension mismatch: expected {self._dim}, got {len(vector)}")
        self.remove(id_)
        self._conn.execute(
            "INSERT INTO vec_items(rowid, embedding) VALUES (?, ?)", (id_, json.dumps(vector))
        )
        self._ids.add(id_)

    def remove(self, id_: int) -> None:
        if id_ in self._ids:
            self._conn.execute("DELETE FROM vec_items WHERE rowid = ?", (id_,))
            self._ids.discard(id_)

    def search(self, query: list[float], top_k: int) -> list[tuple[int, float]]:
        if self._dim is None or not self._ids:
            return []
        rows = self._conn.execute(
            "SELECT rowid, distance FROM vec_items WHERE embedding MATCH ? AND k = ? ORDER BY distance",
            (json.dumps(list(query)), min(top_k, len(self._ids))),
        ).fetchall()
        # vec0 は L2距離を返すため、近さの目安として 0-1 のスコアへ変換する
        return [(rid, 1.0 / (1.0 + dist)) for rid, dist in rows]


def build_vector_backend(preferred: str) -> tuple[VectorBackend, str]:
    """希望バックエンドから開始し、初期化に失敗した層は自動的に読み飛ばす。"""
    order = ["sqlite-vec", "ann", "brute-force"]
    start = order.index(preferred) if preferred in order else 0
    for name in order[start:]:
        try:
            if name == "sqlite-vec":
                return SqliteVecBackend(), "sqlite-vec"
            if name == "ann":
                return RandomProjectionBackend(), "ann"
            return BruteForceBackend(), "brute-force"
        except Exception:
            continue
    return BruteForceBackend(), "brute-force"  # 最終安全網


class VectorIndexManager:
    """
    Singleton オーケストレータ。DemoDataStore の顧客レコードと差分同期しつつ埋め込みをキャッシュする。
    updated_at が変化していないレコードは再埋め込みしない（AI呼び出しコスト削減）。
    """

    def __init__(self, preferred_backend: str) -> None:
        self.backend, self.backend_name = build_vector_backend(preferred_backend)
        self._synced_versions: dict[int, Any] = {}
        self._lock = asyncio.Lock()

    async def sync(self, store: DemoDataStore, ai: AiProvider) -> None:
        async with self._lock:
            current = {c["id"]: c for c in store.list_customers()}
            for cid in list(self._synced_versions.keys()):
                if cid not in current:
                    self.backend.remove(cid)
                    del self._synced_versions[cid]
            for cid, c in current.items():
                version = c.get("updated_at")
                if cid in self._synced_versions and self._synced_versions[cid] == version:
                    continue
                haystack = f"{c['name']} {c.get('company') or ''} {c.get('notes') or ''}"
                vector = await ai.embed(haystack)
                self.backend.index(cid, vector)
                self._synced_versions[cid] = version

    async def search(self, query_vec: list[float], top_k: int) -> list[tuple[int, float]]:
        return self.backend.search(query_vec, top_k)

    def size(self) -> int:
        return len(self._synced_versions)
