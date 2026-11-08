#!/usr/bin/env python
"""
順位評価ゲート。ブリッジの検索品質をデータセットで測る。

bench_bridge.py は速度だけを見る(検索語を本文と同じ語彙から作るので精度は測れない)。
このスクリプトは「期待する文書」を人手で与えたデータセットで、次の 3 点を測る:

  - recall@k / MRR : 関連文書が top_k に入ったか、何位か
  - 権限外漏洩   : 閲覧不可の文書が 1 件も返らなかったか(0 件でなければ失敗)
  - 既定構成の比較 : hybrid / vector-only / bm25-only でどの構成が最も効くか

データセットは JSON。クエリ本文と、各クエリで閲覧する主体(principal)を明示する。
期待文書は source/entity/pk で書く。

    [
      {"q": "来月納品の部品の見積", "who": "sales",
       "relevant": [["legacy_api", "Order", "O001"], ...]}
    ]

使い方:
    cd ai-api-server
    .venv/bin/python scripts/eval_bridge.py --expect-report          # 期待レポートを出す
    .venv/bin/python scripts/eval_bridge.py --kb-dir demo-legacy-system/aisb_profile/legacy_exports \
        --kb-db demo-legacy-system/erp.db
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.bridge.acl import Principal, can_read  # noqa: E402


# データセットの who に書ける主体。実名・実IPは使わない。表示用の識別子だけ。
PRINCIPALS: dict[str, Principal] = {
    "sales_mgr": Principal("eval:sales_mgr", "acme", ("sales",), ("営業部",)),
    "sales_staff": Principal("eval:sales_staff", "acme", ("sales",), ("営業3課",)),
    "accounting": Principal("eval:accounting", "acme", ("accounting",), ("経理部",)),
    "hr": Principal("eval:hr", "acme", ("hr",), ("人事部",)),
    "manager": Principal("eval:manager", "acme", ("manager",), ("経理課",)),
    "purchasing": Principal("eval:purchasing", "acme", ("purchasing",), ("購買部",)),
    "other_tenant": Principal("eval:other_tenant", "other", ("sales", "hr", "dept:*")),
    "anonymous": Principal("anonymous"),
}


def load_dataset(path: str) -> list[dict]:
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or not data:
        raise SystemExit(f"データセットが空か形式が不正です: {path}")
    for i, row in enumerate(data):
        if not row.get("q") or "relevant" not in row:
            raise SystemExit(f"{path} の {i} 番目に q / relevant がありません")
        if row.get("who") and row["who"] not in PRINCIPALS:
            raise SystemExit(f"{path} の {i} 番目の who が不明です: {row['who']} (使えるのは {sorted(PRINCIPALS)})")
    return data


def rank_of(hits, wanted: tuple[str, str, str]) -> int | None:
    for i, (d, _) in enumerate(hits, start=1):
        if (d.source, d.entity, d.pk) == wanted:
            return i
    return None


async def run_eval(rt, dataset: list[dict], top_k: int) -> dict:
    """1 データセットを 1 構成で評価する。漏洩を最優先で検査する。"""
    n = len(dataset)
    recall_hits = 0
    relevant_total = 0
    rr_sum = 0.0
    leaks: list[dict] = []
    misses: list[dict] = []
    no_answer_rows: list[dict] = []

    for row in dataset:
        p = PRINCIPALS[row["who"]] if row.get("who") else PRINCIPALS["anonymous"]
        qvec = await rt._embed(row["q"])
        hits, _filtered, strategy = rt.retriever.search(
            p, qvec, top_k, set(row["entities"]) if row.get("entities") else None, query=row["q"])
        # ACL 不変条件: 返った文書はすべて閲覧可能でなければならない
        assert all(can_read(p, d.acl) for d, _ in hits), f"漏洩(ACL): {row['q']} {strategy}"
        assert len(hits) <= top_k

        relevant = [tuple(r) for r in row["relevant"]]
        relevant_total += len(relevant)
        ranks = {r: rank_of(hits, r) for r in relevant}
        found = [r for r, k in ranks.items() if k is not None]
        recall_hits += len(found)
        if found:
            rr_sum += 1.0 / min(ranks[r] for r in found)
        if not relevant and not hits:
            no_answer_rows.append(row)
        if len(found) < len(relevant):
            misses.append({"q": row["q"], "missing": [list(r) for r in relevant if ranks[r] is None],
                           "got": [f"{d.source}/{d.entity}/{d.pk}" for d, _ in hits]})

    # 回答不能語(期待文書なし)は「0 件を返すこと」が正解。カバレッジを上げるとノイズ文書が
    # 根拠に流れ込むので、この的中も測る。
    no_answer_total = sum(1 for row in dataset if not row["relevant"])
    no_answer_ok = sum(1 for row in dataset if not row["relevant"] and row in no_answer_rows)

    return {
        "queries": n,
        "recall_at_k": round(recall_hits / relevant_total, 3) if relevant_total else 0.0,
        "no_answer_rate": round(no_answer_ok / no_answer_total, 3) if no_answer_total else None,
        "mrr": round(rr_sum / n, 3) if n else 0.0,
        "leaks": leaks,
        "misses": misses,
    }


def _retriever_variant(rt, kind: str):
    """既定構成を切り替えた 1 回だけの比較用。本番の設定は変えない。"""
    from app.bridge.retriever import Retriever
    base = rt.retriever
    r = Retriever(base.preferred_backend, exact_threshold=base.exact_threshold,
                  oversample=base.oversample, hybrid=base.hybrid,
                  vector_weight=base.vector_weight, lexical_weight=base.lexical_weight,
                  rrf_k=base.rrf_k, min_matched_terms=base.min_matched_terms,
                  min_score_ratio=base.min_score_ratio, vector_only_hits=base.vector_only_hits)
    if kind == "vector-only":
        r.hybrid = False
    elif kind == "bm25-only":
        r.vector_weight = 0.0
        r.lexical_weight = 1.0
    r.load(rt.store.all_docs())
    return r


async def eval_variants(rt, dataset, top_k, variants):
    out = {}
    real = rt.retriever
    for kind in variants:
        rt.retriever = real if kind == "default" else _retriever_variant(rt, kind)
        out[kind] = await run_eval(rt, dataset, top_k)
    rt.retriever = real
    return out


def assert_gate(report: dict, min_recall: float) -> None:
    problems = []
    for kind, r in report.items():
        if r["leaks"]:
            problems.append(f"{kind}: 権限外漏洩 {len(r['leaks'])} 件")
        if r["recall_at_k"] < min_recall:
            problems.append(f"{kind}: recall@k={r['recall_at_k']} < {min_recall}")
    if problems:
        raise SystemExit("評価ゲート失敗:\n  - " + "\n  - ".join(problems))


def build_runtime_with_kb(kb_dir: str | None, kb_db: str | None):
    """./-外からの最小構成のランタイム。ドメインのプロファイルは読まない(評価専用)。"""
    from app.bridge.runtime import BridgeRuntime
    from app.services.ai_client import MockProvider

    tmp = tempfile.mkdtemp(prefix="aisb_eval_")
    profile = {"store": {"path": os.path.join(tmp, "eval.db")},
               "retrieval": {"min_matched_terms": 1, "min_score_ratio": 0, "vector_only_hits": True},
               "sources": []}
    if kb_dir:
        profile["sources"].append({"name": "files", "type": "file",
                                   "config": {"base_dir": kb_dir, "encoding": "cp932"},
                                   "entities": [{"name": "Shipment", "pk": "ShipNo", "title": "ShipNo",
                                                 "text": ["ShipDate", "CustomerName", "ItemName", "Qty", "Dept"],
                                                 "options": {"path": "shipments_fixed.txt", "format": "fixed",
                                                             "skip_lines": 1, "columns": [
                                                                 {"name": "ShipNo", "start": 0, "length": 10},
                                                                 {"name": "ShipDate", "start": 10, "length": 8},
                                                                 {"name": "CustomerName", "start": 18, "length": 20},
                                                                 {"name": "ItemName", "start": 38, "length": 30},
                                                                 {"name": "Qty", "start": 68, "length": 6},
                                                                 {"name": "Dept", "start": 74, "length": 12}]}}]})
    if kb_db:
        profile["sources"].append({"name": "db", "type": "sql", "config": {"dsn": f"sqlite:///{kb_db}"},
                                   "entities": [{"name": "Employee", "pk": "Id", "title": "Name",
                                                 "text": ["Name", "Department", "Position", "HireDate"],
                                                 "options": {"query": """
            SELECT json_extract(value,'$.Id') AS Id, json_extract(value,'$.Name') AS Name,
                   json_extract(value,'$.Department') AS Department,
                   json_extract(value,'$.Position') AS Position,
                   json_extract(value,'$.HireDate') AS HireDate
            FROM employees"""}}]})
    async def embed(text: str) -> list[float]:
        return await MockProvider().embed(text)
    return BridgeRuntime(profile, embed=embed, embedder_id="ngram-hash-64",
                         default_store_path=profile["store"]["path"])


def build_runtime_with_profile(path: str, tmpdir: bool = True):
    """bridge.yaml をそのまま読む。評価ごとに空の store にしたいので、既定では store だけ差し替える。"""
    import yaml
    from app.bridge.runtime import BridgeRuntime
    with open(path, encoding="utf-8") as f:
        profile = yaml.safe_load(f) or {}
    if tmpdir:
        tmp = tempfile.mkdtemp(prefix="aisb_eval_")
        profile["store"] = {"path": os.path.join(tmp, "eval.db")}
    # 評価は再現性を優先して擬似埋め込みのまま(実モデルは --embedder gemini で後から差し込む)
    from app.services.ai_client import MockProvider
    async def embed(text: str) -> list[float]:
        return await MockProvider().embed(text)
    return BridgeRuntime(profile, embed=embed, embedder_id="ngram-hash-64",
                         profile_path=path, default_store_path=profile["store"]["path"])


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dataset", default=os.path.join(os.path.dirname(__file__), "..", "evals",
                                                      "retrieval_gate.json"))
    ap.add_argument("--top-k", type=int, default=5)
    ap.add_argument("--min-recall", type=float, default=0.8)
    ap.add_argument("--variants", default="default,vector-only,bm25-only")
    ap.add_argument("--hybrid", choices=["on", "off"], default="on",
                    help="プロファイルの retrieval 設定に関わらずハイブリッド融合を強制する(切り分け用)")
    ap.add_argument("--verbose", action="store_true", help="不的中の内訳を出す")
    ap.add_argument("--profile", help="導入先プロファイル(bridge.yaml)。ERP デモ等の実構成で測る")
    ap.add_argument("--kb-dir")
    ap.add_argument("--kb-db")
    ap.add_argument("--embedder", default="mock",
                    help="mock(既定・オフライン) / gemini(GEMINI_API_KEY が必要)")
    ap.add_argument("--json", action="store_true", help="結果を JSON(1 行)で出す")
    ap.add_argument("--expect-report", action="store_true",
                    help="実行できない環境で、必要な入力と期待値の形だけを示す")
    args = ap.parse_args()

    if args.expect_report:
        print(json.dumps({
            "dataset": args.dataset,
            "needs": ["橋のプロファイル (--profile) または 合成 KB (--kb-dir/--kb-db) のどちらか"],
            "measures": ["recall@k", "MRR", "ACL 漏洩件数(必ず 0)"],
            "gate": {"leaks": 0, "min_recall_at_k": args.min_recall},
        }, ensure_ascii=False, indent=2))
        return 0

    dataset = load_dataset(args.dataset)
    if args.profile:
        rt = build_runtime_with_profile(args.profile)
    else:
        rt = build_runtime_with_kb(args.kb_dir, args.kb_db)
    if args.embedder == "gemini":
        from app.services.ai_client import GeminiProvider
        if not os.environ.get("GEMINI_API_KEY"):
            raise SystemExit("GEMINI_API_KEY が未設定です。実埋め込みで測るにはキーが必要です")
        if not os.environ.get("AISB_EVAL_ALLOW_REMOTE"):
            # 業務データを外部へ送る前に、利用者が明示的に許可したことを要求する
            raise SystemExit("実埋め込みは対象データを外部APIへ送ります。AISB_EVAL_ALLOW_REMOTE=1 で許可してください")
        provider = GeminiProvider(os.environ["GEMINI_API_KEY"])
        # 文書は embed("doc")、検索語は embed_query("query") と体裁を分ける(非対称検索)
        rt._embed = rt.engine._embed = provider.embed
        rt._embed_query = provider.embed_query
        rt.engine.embedder_id = provider.embedder_id
        rt.store.reset_embeddings(provider.embedder_id)
    elif args.embedder != "mock":
        raise SystemExit(f"unknown --embedder: {args.embedder}")
    asyncio.run(rt.sync("eval"))
    if rt.retriever.size() == 0:
        raise SystemExit("取り込んだ文書が 0 件です(--kb-dir / --kb-db を指定してください)")

    if args.hybrid == "on":
        # 既定はハイブリッド融合 ON。プロファイルの retrieval.sync_interval などは触らない。
        rt.retriever.hybrid = True

    variants = [v.strip() for v in args.variants.split(",") if v.strip()]
    report = asyncio.run(eval_variants(rt, dataset, args.top_k, variants))
    report = {k: {**v, "embedder": rt.engine.embedder_id} for k, v in report.items()}

    if args.json:
        print(json.dumps(report, ensure_ascii=False))
    else:
        print(f"embedder={rt.engine.embedder_id} docs={rt.retriever.size()} queries={len(dataset)} top_k={args.top_k}")
        for kind, r in report.items():
            na = "n/a" if r["no_answer_rate"] is None else f"{r['no_answer_rate']:.2f}"
            print(f"  {kind:12s} recall@{args.top_k}={r['recall_at_k']:.3f}  MRR={r['mrr']:.3f}  "
                  f"回答不能語の棄却={na}  漏洩={len(r['leaks'])}件")
        if args.verbose:
            for m in report["default"]["misses"]:
                print(f"  MISS {m['q']}: 期待 {m['missing']} / 取得 {m['got'][:5]}")
    assert_gate(report, args.min_recall)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
