"""
AI自動生成クロス分析サービス
================================
背景: cross_analysis_service.py の3レポート(与信リスク/在庫逼迫/滞留債権)は
すべてハードコードされた専用関数であり、「新しい業務観点の分析」を追加するには
コード変更が要る。ユーザーからは「AIが自動でレポートを生成して要約もしてほしい」
という要望を受けたが、単純に「AIに自由にJOIN条件やSQLを生成させる」方式は
5.4.11(nlsql_service.py)で直面したのと同じ安全性問題がより深刻な形で再燃する:
単一エンティティのフィルタと違い、複数エンティティの「どれとどれを」「どの項目を
キーに」結合するかまでAIに自由決定させると、無関係な項目同士を誤って結合する
(意味のない集計になる)リスクが高い。

そこで nlsql_service と同じ「構造化パラメータ(JSON)のみをAIに生成させ、
ホワイトリスト検証を通過したものだけをコード側で安全に実行する」路線を、
2エンティティ・GROUP BY・集計(SUM/COUNT/AVG/MIN/MAX)まで一般化した形で採用する。

具体的な安全策:
  1. JOIN可能な組み合わせ(どのentityのどの外部キーがどのentityのIdを指すか)は
     JOIN_GRAPH として本コードにハードコードされたものだけを許可する。AIは
     「主エンティティ」「副エンティティ」の"名前"を選ぶだけで、実際の結合キー
     (外部キーのフィールド名)はAIには一切生成させず、常にこのグラフから
     コード側で決定する(=誤ったキーでの結合が原理的に起こらない)。
  2. フィルタ条件のfield/opはnlsql_serviceと同じホワイトリスト方式
     (filter_ops.ALLOWED_OPS)で検証し、evalも生SQLも使わない。
  3. group_by/metric_fieldは、実際に取得した行データに存在するフィールド名
     でなければ却下する(存在しないフィールド名をでっち上げても集計に使われない)。
  4. 集計・グルーピング自体の実装はAI非依存(このモジュール内の純粋なPythonロジック)。
     AIが関与するのは「どのパラメータで集計するか」の決定と、結果への解釈
     コメント(insight_service.interpret_cross_analysis、既存の3レポートと共通、
     オプトイン)のみ。
"""
import asyncio
from datetime import datetime

from app.config import Settings
from app.services import ai_json_util, filter_ops, legacy_client
from app.services.ai_client import AiProvider
from app.services.nlsql_service import NLSQLService

_TOP_N_CHART = 10
_SCHEMA_SAMPLE_ROWS = 20  # フィールド名+低カーディナリティ値ヒント抽出用(集計自体には使わない)
ALLOWED_AGGS = {"sum", "count", "avg", "min", "max"}

# ---------------------------------------------------------------------------
# JOIN_GRAPH: (主エンティティ, 副エンティティ) -> 主エンティティ側の外部キー項目名
# 「主エンティティ」= 明細/トランザクション側(多)、「副エンティティ」= マスタ側(一)。
# ここに列挙された組み合わせ以外での結合はAIが何を生成しても拒否される。
# ---------------------------------------------------------------------------
JOIN_GRAPH: dict[tuple[str, str], str] = {
    ("Order", "Customer"): "CustomerId",
    ("Estimate", "Customer"): "CustomerId",
    ("Invoice", "Customer"): "CustomerId",
    ("Invoice", "Order"): "OrderId",
    ("PurchaseOrder", "Supplier"): "SupplierId",
    ("InventoryTransaction", "Product"): "ProductId",
    ("GoodsReceipt", "Product"): "ProductId",
    ("GoodsReceipt", "Supplier"): "SupplierId",
    ("Profit", "Product"): "ProductId",
}


class DynamicAnalysisService:
    def __init__(self, settings: Settings, ai: AiProvider):
        self.settings = settings
        self.ai = ai

    # -----------------------------------------------------------------
    # 1. 全entityのフィールド名+値ヒントを集めてAIプロンプト用スキーマ情報を作る
    #    (13entity分の軽量な並列フェッチ。デモ規模のインメモリ legacy なので許容範囲)
    # -----------------------------------------------------------------
    async def _fetch_schema(self) -> tuple[dict[str, str], dict[str, list[dict]]]:
        entities_meta_list = await legacy_client.fetch_entities(self.settings)
        entities_meta = {e["entity"]: e["label"] for e in entities_meta_list}
        results = await asyncio.gather(
            *[
                legacy_client.fetch_rows(self.settings, name, limit=_SCHEMA_SAMPLE_ROWS)
                for name in entities_meta
            ],
            return_exceptions=True,
        )
        schema_rows: dict[str, list[dict]] = {}
        for name, result in zip(entities_meta, results):
            if isinstance(result, Exception):
                schema_rows[name] = []
                continue
            rows, _ = result
            schema_rows[name] = rows
        return entities_meta, schema_rows

    # -----------------------------------------------------------------
    # 2. プロンプト組み立て(entity一覧+フィールド名+値ヒント+許可JOIN一覧)
    # -----------------------------------------------------------------
    @staticmethod
    def _build_prompt(question: str, entities_meta: dict[str, str], schema_rows: dict[str, list[dict]]) -> str:
        entity_lines = []
        for name, label in entities_meta.items():
            rows = schema_rows.get(name) or []
            fields = sorted(rows[0].keys()) if rows else []
            hints = NLSQLService._field_value_hints(rows) if rows else {}
            hint_parts = [f"{f}の値例:[{','.join(vs)}]" for f, vs in hints.items()]
            hint_str = f" ({'; '.join(hint_parts)})" if hint_parts else ""
            entity_lines.append(f"- {name}({label}): 項目=[{', '.join(fields)}]{hint_str}")

        join_lines = [
            f"- {primary}.{fk} → {secondary}.Id (主エンティティ={primary}, 副エンティティ={secondary})"
            for (primary, secondary), fk in JOIN_GRAPH.items()
        ]

        return (
            "あなたは基幹システムのデータ分析アシスタントです。以下のエンティティ一覧"
            "(各項目名・低カーディナリティ項目の実際の値の例)から、ユーザーの質問に"
            "答えるための「集計パラメータ」をJSONで生成してください。\n\n"
            "【エンティティ一覧】\n" + "\n".join(entity_lines) + "\n\n"
            "【結合可能な組み合わせ(これ以外の組み合わせで結合してはならない)】\n"
            + "\n".join(join_lines) + "\n\n"
            f"ユーザーの質問:「{question}」\n\n"
            "以下のJSON形式のみで出力してください(説明文・コードブロック記法・SQL文は"
            "一切不要。JSON以外の文字は出力しないこと):\n"
            "{\n"
            '  "primary_entity": "上記エンティティ名のいずれか(集計の母体となる方)",\n'
            '  "secondary_entity": "結合が必要な場合のみ、上記の許可された組み合わせの'
            '副エンティティ名。不要ならnull",\n'
            '  "filters": [{"field": "項目名", "op": "eq|ne|gt|gte|lt|lte|contains|in", '
            '"value": 値}],\n'
            '  "group_by": "集計の軸にする項目名",\n'
            '  "metric_field": "合計/平均/最大/最小の対象にする数値項目名。件数を数える'
            'だけならnull",\n'
            '  "agg": "sum|count|avg|min|max",\n'
            '  "sort_dir": "asc|desc",\n'
            '  "limit": 整数(既定15, 最大50),\n'
            '  "chart_label": "チャート凡例用の短い日本語ラベル"\n'
            "}\n"
            "重要な制約:\n"
            "1. secondary_entityの項目を filters/group_by/metric_field で参照する場合は"
            ' 必ず "副エンティティ名.項目名" の形式(例: "Customer.Industry")で書くこと。'
            "primary_entityの項目はそのままの項目名で書くこと。\n"
            "2. secondary_entityを指定する場合、必ず上記の許可された組み合わせから"
            "選ぶこと(順序も守ること。主エンティティ側を primary_entity にすること)。\n"
            "3. 文字列のvalueは値の例に実際に出現する表記をそのまま使うこと"
            "(英訳・意訳しないこと。完全一致する値が見当たらない場合はopをcontainsにすること)。\n"
            "4. 件数を数えたいだけの質問(例:「〜が多い順」で金額等の指定がない)ではagg=\"count\"にし、"
            "metric_fieldはnullにすること。"
        )

    # -----------------------------------------------------------------
    # 3. ホワイトリスト検証(ここを通過したものだけが実際に実行される)
    # -----------------------------------------------------------------
    @staticmethod
    def _resolve_field_ref(raw_field, primary_fields: set, secondary: str | None, secondary_fields: set):
        """"field" または "SecondaryEntity.field" 形式の文字列を
        {"scope": "primary"|"secondary", "field": bare_field} に解決する。
        存在しない項目・許可されていないentity参照はNoneを返す(=呼び出し側で無視)。"""
        if not isinstance(raw_field, str) or not raw_field:
            return None
        if secondary and raw_field.startswith(f"{secondary}."):
            bare = raw_field[len(secondary) + 1 :]
            return {"scope": "secondary", "field": bare} if bare in secondary_fields else None
        return {"scope": "primary", "field": raw_field} if raw_field in primary_fields else None

    def _validate_spec(self, raw: dict, entities_meta: dict, schema_rows: dict) -> tuple[dict | None, list[str]]:
        warnings: list[str] = []
        entity_names = set(entities_meta.keys())

        primary = raw.get("primary_entity")
        if primary not in entity_names:
            return None, [f"不明な主エンティティ '{primary}' が指定されたため分析できません"]
        if not schema_rows.get(primary):
            return None, [f"'{entities_meta[primary]}'のデータが空のため分析できません"]

        secondary = raw.get("secondary_entity")
        if secondary is not None:
            if secondary not in entity_names:
                warnings.append(f"不明な副エンティティ '{secondary}' は無視しました")
                secondary = None
            elif (primary, secondary) not in JOIN_GRAPH:
                warnings.append(
                    f"'{primary}'と'{secondary}'は結合できない組み合わせのため副エンティティを無視しました"
                )
                secondary = None
            elif not schema_rows.get(secondary):
                warnings.append(f"'{entities_meta[secondary]}'のデータが空のため副エンティティを無視しました")
                secondary = None

        primary_fields = set(schema_rows[primary][0].keys())
        secondary_fields = set(schema_rows[secondary][0].keys()) if secondary else set()

        def resolve(raw_field):
            return self._resolve_field_ref(raw_field, primary_fields, secondary, secondary_fields)

        filters = []
        for c in raw.get("filters") or []:
            if not isinstance(c, dict):
                continue
            ref = resolve(c.get("field"))
            op = c.get("op")
            if not ref or op not in filter_ops.ALLOWED_OPS:
                warnings.append(f"不正な絞り込み条件 {c} は無視しました")
                continue
            filters.append({**ref, "op": op, "value": c.get("value")})

        group_by = resolve(raw.get("group_by"))
        if not group_by:
            warnings.append(f"グループ化項目 '{raw.get('group_by')}' が不正なため集計できません")

        agg = raw.get("agg") if raw.get("agg") in ALLOWED_AGGS else "count"
        metric = resolve(raw.get("metric_field")) if agg != "count" else None
        if agg != "count" and not metric:
            warnings.append("集計対象の数値項目が不正なため件数(count)に切り替えます")
            agg = "count"
            metric = None

        sort_dir = "asc" if raw.get("sort_dir") == "asc" else "desc"
        limit = raw.get("limit")
        if not isinstance(limit, int) or limit <= 0 or limit > 50:
            limit = 15

        chart_label = raw.get("chart_label")
        if not isinstance(chart_label, str) or not chart_label.strip():
            chart_label = "件数" if agg == "count" else (metric["field"] if metric else "集計値")

        spec = {
            "primary_entity": primary,
            "secondary_entity": secondary,
            "filters": filters,
            "group_by": group_by,
            "metric": metric,
            "agg": agg,
            "sort_dir": sort_dir,
            "limit": limit,
            "chart_label": chart_label[:40],
        }
        return spec, warnings

    # -----------------------------------------------------------------
    # 4. 検証済みspecの安全な実行(eval不使用、JOIN_GRAPH固定キーのみ使用)
    # -----------------------------------------------------------------
    @staticmethod
    def _resolve_value(row: dict, sec_row: dict | None, ref: dict):
        if ref["scope"] == "secondary":
            return sec_row.get(ref["field"]) if sec_row else None
        return row.get(ref["field"])

    async def generate(self, question: str) -> dict:
        entities_meta, schema_rows = await self._fetch_schema()
        prompt = self._build_prompt(question, entities_meta, schema_rows)
        ai_text = await self.ai.complete(prompt)
        raw = ai_json_util.extract_json(ai_text)

        warnings: list[str] = []
        if not raw:
            warnings.append("AI応答から分析条件を解釈できませんでした")
        spec, spec_warnings = self._validate_spec(raw, entities_meta, schema_rows)
        warnings.extend(spec_warnings)

        empty_chart = {"type": "ranked-bar", "unit": "", "categories": [], "series": []}
        if spec is None or spec["group_by"] is None:
            return {
                "report": "generated", "label": "AI自動生成レポート", "question": question,
                "spec": spec, "generated_at": datetime.utcnow(),
                "summary": {"matched_rows": 0, "group_count": 0}, "chart": empty_chart,
                "rows": [], "warnings": warnings, "provider": self.ai.name,
            }

        primary_rows, primary_label = await legacy_client.fetch_rows(self.settings, spec["primary_entity"])
        sec_index: dict = {}
        sec_label = None
        fk_field = None
        if spec["secondary_entity"]:
            sec_rows, sec_label = await legacy_client.fetch_rows(self.settings, spec["secondary_entity"])
            sec_index = {r.get("Id"): r for r in sec_rows}
            fk_field = JOIN_GRAPH[(spec["primary_entity"], spec["secondary_entity"])]

        matched = []
        for row in primary_rows:
            sec_row = sec_index.get(row.get(fk_field)) if fk_field else None
            if all(
                filter_ops.match_value(self._resolve_value(row, sec_row, f), f["op"], f["value"])
                for f in spec["filters"]
            ):
                matched.append((row, sec_row))

        groups: dict[str, dict] = {}
        skipped_non_numeric = 0
        for row, sec_row in matched:
            gval = self._resolve_value(row, sec_row, spec["group_by"])
            if gval is None:
                continue
            gkey = str(gval)
            entry = groups.setdefault(gkey, {"group": gkey, "count": 0, "metric_sum": 0.0, "metric_values": []})
            entry["count"] += 1
            if spec["agg"] != "count" and spec["metric"]:
                mval = self._resolve_value(row, sec_row, spec["metric"])
                try:
                    mval_f = float(mval)
                    entry["metric_sum"] += mval_f
                    entry["metric_values"].append(mval_f)
                except (TypeError, ValueError):
                    skipped_non_numeric += 1
        if skipped_non_numeric:
            warnings.append(f"集計項目が数値でない{skipped_non_numeric}件を除外しました")

        def group_value(entry):
            if spec["agg"] == "sum":
                return entry["metric_sum"]
            if spec["agg"] == "avg":
                return entry["metric_sum"] / len(entry["metric_values"]) if entry["metric_values"] else 0.0
            if spec["agg"] == "min":
                return min(entry["metric_values"]) if entry["metric_values"] else 0.0
            if spec["agg"] == "max":
                return max(entry["metric_values"]) if entry["metric_values"] else 0.0
            return entry["count"]  # count既定

        result_rows = [
            {"group": e["group"], "value": round(group_value(e), 2), "matched_count": e["count"]}
            for e in groups.values()
        ]
        result_rows.sort(key=lambda r: r["value"], reverse=(spec["sort_dir"] == "desc"))
        result_rows = result_rows[: spec["limit"]]
        if not result_rows:
            warnings.append("条件に一致するデータがありませんでした")

        top = result_rows[:_TOP_N_CHART]
        unit = "件" if spec["agg"] == "count" else ""
        chart = {
            "type": "ranked-bar", "unit": unit,
            "categories": [r["group"] for r in top],
            "series": [{"label": spec["chart_label"], "values": [r["value"] for r in top]}],
        }
        summary = {
            "matched_rows": len(matched),
            "group_count": len(result_rows),
            "primary_entity": primary_label,
            "secondary_entity": sec_label or "-",
            "agg": spec["agg"],
        }
        label = f"{primary_label}" + (f"×{sec_label}" if sec_label else "") + " 分析(AI自動生成)"
        return {
            "report": "generated", "label": label, "question": question,
            "spec": spec, "generated_at": datetime.utcnow(),
            "summary": summary, "chart": chart, "rows": result_rows,
            "warnings": warnings, "provider": self.ai.name,
        }
