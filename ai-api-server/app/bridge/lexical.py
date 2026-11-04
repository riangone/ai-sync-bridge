"""
語彙(BM25)インデックス。ベクトル検索と併用するハイブリッド検索の片翼。

なぜ必要か:
  閉域・オンプレ導入では埋め込みAPIが使えず、n-gram ハッシュの擬似埋め込みに
  フォールバックすることが多い。その場合ベクトル類似度だけでは「経理部」「課長」の
  ような業務キーワードが効かない。BM25 を併用すれば、埋め込みモデルなしでも
  実用的な検索精度が出る(良い埋め込みがある場合も固有名詞・コード値の一致に強い)。

トークン化: 日本語は分かち書きせず「文字バイグラム」(形態素解析器への依存なし)。
英数字は連続部分を1語として小文字化。依存ライブラリなし・メモリ上の転置インデックス。
"""
from __future__ import annotations

import math
import re
from collections import Counter, defaultdict

_ALNUM = re.compile(r"[0-9A-Za-z_\-\.]+")
_CJK = re.compile(r"[぀-ヿ㐀-鿿豈-﫿ｦ-ﾟ々ー]+")
# DocRecord.body は "Field:value Field:value" 形式。フィールド名自体は検索語にしない。
_FIELD_LABEL = re.compile(r"(?:(?<=\s)|^)[A-Za-z_][A-Za-z0-9_]*:")


def tokenize(text: str) -> list[str]:
    text = _FIELD_LABEL.sub(" ", text or "")
    toks: list[str] = [m.group(0).lower() for m in _ALNUM.finditer(text)]
    for m in _CJK.finditer(text):
        run = m.group(0)
        if len(run) == 1:
            toks.append(run)
        else:
            toks.extend(run[i:i + 2] for i in range(len(run) - 1))
    return toks


class LexicalIndex:
    def __init__(self, k1: float = 1.2, b: float = 0.75):
        self.k1, self.b = k1, b
        self._tf: dict[int, Counter] = {}
        self._len: dict[int, int] = {}
        self._postings: dict[str, set[int]] = defaultdict(set)
        self._total_len = 0

    def __len__(self) -> int:
        return len(self._tf)

    def upsert(self, doc_id: int, text: str) -> None:
        self.remove(doc_id)
        tf = Counter(tokenize(text))
        self._tf[doc_id] = tf
        n = sum(tf.values())
        self._len[doc_id] = n
        self._total_len += n
        for t in tf:
            self._postings[t].add(doc_id)

    def remove(self, doc_id: int) -> None:
        tf = self._tf.pop(doc_id, None)
        if tf is None:
            return
        self._total_len -= self._len.pop(doc_id, 0)
        for t in tf:
            s = self._postings.get(t)
            if s is not None:
                s.discard(doc_id)
                if not s:
                    del self._postings[t]

    def scores(self, query: str, allowed: set[int] | None = None) -> dict[int, float]:
        """BM25 スコア。allowed を渡すとその文書集合だけで統計(N/df/平均長)を取り採点する。
        全体統計を使うと閲覧不可文書の有無でスコアが変わり、存在が推測できてしまうため。"""
        return self.match(query, allowed)[0]

    def match(self, query: str, allowed: set[int] | None = None) -> tuple[dict[int, float], dict[int, int]]:
        """(BM25 スコア, 文書ごとの一致した質問語の種類数)。統計の扱いは scores と同じ。"""
        if allowed is None:
            universe_n, total = len(self._tf), self._total_len
        else:
            allowed = {d for d in allowed if d in self._tf}
            universe_n, total = len(allowed), sum(self._len[d] for d in allowed)
        if not universe_n:
            return {}, {}
        avg = (total / universe_n) or 1.0
        scores: dict[int, float] = defaultdict(float)
        matched: dict[int, int] = defaultdict(int)
        for t in set(tokenize(query)):
            post = self._postings.get(t)
            if not post:
                continue
            if allowed is not None:
                post = post & allowed
                if not post:
                    continue
            idf = math.log(1 + (universe_n - len(post) + 0.5) / (len(post) + 0.5))
            for d in post:
                f = self._tf[d][t]
                denom = f + self.k1 * (1 - self.b + self.b * self._len[d] / avg)
                scores[d] += idf * f * (self.k1 + 1) / denom
                matched[d] += 1
        return dict(scores), dict(matched)
