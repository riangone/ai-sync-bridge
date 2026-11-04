"""
Retriever: 権限フィルタ付きベクトル検索。

方針「ACLフィルタは結果を返す前に必ず適用」:
  - 閲覧可能文書が少ない(<= exact_threshold) → 閲覧可能文書だけを総当たり(厳密・漏洩なし)
  - 多い → 3層バックエンド(sqlite-vec/ann/brute-force)で多めに候補を取り、ACLで絞る。
           絞った結果が top_k に満たなければ総当たりへフォールバック(リコール保証)。
どの経路でも、閲覧不可の文書がスコア計算結果に混入して返ることはない。

ハイブリッド(既定ON): ベクトル順位と BM25 順位(lexical.py)を RRF で融合する。
BM25 も閲覧可能文書の集合だけで統計を取るため、ACL 不変条件はそのまま保たれる。

関連度の足切り: 質問と関係ない文書で top_k を埋めると、比較検索にノイズが混ざり、RAG では
無駄な LLM 呼び出しになる。長い質問で 1 語しか一致しない文書(「社員」だけ一致など)と、
最上位より大きくスコアが低い文書を落とし、擬似埋め込みの場合は語が一致しない文書をベクトル
だけで通さない(0 件なら RAG は LLM を呼ばない)。比率でなく一致語の種類数で見るのは、
「〜を教えてください」のような語が多い質問でも基準が変わらないようにするため。
"""
from __future__ import annotations

import math
import threading

from app.bridge.acl import Principal, can_read
from app.bridge.lexical import LexicalIndex, tokenize
from app.bridge.store import DocRecord
from app.services.vector_index import VectorBackend, build_vector_backend


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-9
    nb = math.sqrt(sum(y * y for y in b)) or 1e-9
    return dot / (na * nb)


class Retriever:
    def __init__(self, preferred_backend: str, exact_threshold: int = 5000, oversample: int = 10,
                 hybrid: bool = True, vector_weight: float = 1.0, lexical_weight: float = 1.0,
                 rrf_k: int = 60, min_matched_terms: int = 1, short_query_terms: int = 3,
                 min_score_ratio: float = 0.0,
                 vector_only_hits: bool = True):
        self.preferred_backend = preferred_backend
        self.exact_threshold = exact_threshold
        self.oversample = oversample
        self.hybrid = hybrid
        self.vector_weight = vector_weight
        self.lexical_weight = lexical_weight
        self.rrf_k = rrf_k
        self.min_matched_terms = min_matched_terms
        self.short_query_terms = short_query_terms
        self.min_score_ratio = min_score_ratio
        self.vector_only_hits = vector_only_hits
        self.lexical = LexicalIndex()
        self._lock = threading.RLock()
        self._docs: dict[int, DocRecord] = {}
        self.backend: VectorBackend
        self.backend_name: str
        self.backend, self.backend_name = build_vector_backend(preferred_backend)

    def load(self, docs: list[DocRecord]) -> None:
        with self._lock:
            self.backend, self.backend_name = build_vector_backend(self.preferred_backend)
            self._docs = {}
            self.lexical = LexicalIndex()
            for d in docs:
                self._put(d)

    def _put(self, d: DocRecord) -> None:
        try:
            self.backend.index(d.doc_id, d.vector)
        except ValueError:
            # 次元不一致(埋め込みモデル変更直後など)。総当たり経路では引き続き検索可能。
            pass
        self._docs[d.doc_id] = d
        self.lexical.upsert(d.doc_id, f"{d.title} {d.body}")

    def upsert(self, d: DocRecord) -> None:
        with self._lock:
            self.backend.remove(d.doc_id)
            self._put(d)

    def remove(self, doc_id: int) -> None:
        with self._lock:
            self.backend.remove(doc_id)
            self._docs.pop(doc_id, None)
            self.lexical.remove(doc_id)

    def size(self) -> int:
        return len(self._docs)

    def search(self, principal: Principal, qvec: list[float], top_k: int,
               entities: set[str] | None = None, query: str = ""
               ) -> tuple[list[tuple[DocRecord, float]], int, str]:
        """returns (hits, acl_filtered_count, strategy)"""
        with self._lock:
            docs = self._docs

            def visible(d: DocRecord) -> bool:
                return (entities is None or d.entity in entities) and can_read(principal, d.acl)

            in_scope = [d for d in docs.values() if entities is None or d.entity in entities]
            allowed = [d for d in in_scope if can_read(principal, d.acl)]
            filtered = len(in_scope) - len(allowed)
            if not allowed:
                return [], filtered, "empty"

            use_lex = self.hybrid and bool(query.strip())
            # 融合する場合は各系統から多めに候補を取る
            n_cand = top_k * self.oversample if use_lex else top_k

            vec: list[tuple[DocRecord, float]] | None = None
            strategy = "exact-prefilter"
            if len(allowed) > self.exact_threshold:
                cand = self.backend.search(qvec, min(len(docs), n_cand * self.oversample))
                hits = [(docs[i], s) for i, s in cand if i in docs and visible(docs[i])][:n_cand]
                if len(hits) >= top_k:
                    vec, strategy = hits, f"{self.backend_name}+acl-postfilter"
            if vec is None:
                vec = [(d, _cosine(qvec, d.vector)) for d in allowed if len(d.vector) == len(qvec)]
                vec.sort(key=lambda x: x[1], reverse=True)
                vec = vec[:n_cand]

            if not use_lex:
                return vec[:top_k], filtered, strategy

            lex_scores, matched = self.lexical.match(query, {d.doc_id for d in allowed})
            if lex_scores:
                floor = max(lex_scores.values()) * self.min_score_ratio
                need = 1 if len(set(tokenize(query))) <= self.short_query_terms else self.min_matched_terms
                lex_scores = {i: s for i, s in lex_scores.items() if s >= floor and matched[i] >= need}
            if not self.vector_only_hits:
                vec = [(d, s) for d, s in vec if d.doc_id in lex_scores]
            if not lex_scores:
                return vec[:top_k], filtered, strategy
            lex = sorted(lex_scores.items(), key=lambda x: x[1], reverse=True)[:n_cand]

            fused: dict[int, float] = {}
            for rank, (d, _) in enumerate(vec):
                fused[d.doc_id] = fused.get(d.doc_id, 0.0) + self.vector_weight / (self.rrf_k + rank + 1)
            for rank, (doc_id, _) in enumerate(lex):
                fused[doc_id] = fused.get(doc_id, 0.0) + self.lexical_weight / (self.rrf_k + rank + 1)
            ranked = sorted(fused.items(), key=lambda x: x[1], reverse=True)[:top_k]
            # docs は ACL 済み allowed 由来の id のみ(vec/lex とも allowed から生成)
            return [(docs[i], s) for i, s in ranked], filtered, strategy + "+bm25"
