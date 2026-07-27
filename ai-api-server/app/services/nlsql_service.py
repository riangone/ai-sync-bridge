"""
自然言語 → 構造化フィルタ 変換サービス (5.4.11 差分実装)
==========================================================
仕様書5.4.11の原案は「AIが生成したSQLを直接実行する」方式(POST /api/query)を
規定しているが、以下の理由でそのままは採用していない:

  1. データ層が実SQLエンジンを持たない。demo-legacy-system側の13エンティティは
     インメモリdict(data.py)であり、生SQL文字列を投げられる先が存在しない。
  2. 生成AIの出力を検証なしに実行するのはインジェクション/誤操作のリスクが高い。

そこで本実装では、AIには「構造化フィルタ(JSON)」だけを生成させ、実際の絞り込みは
このモジュールがホワイトリスト検証を通過した条件のみをPythonで評価する
(evalも生SQLも一切使わない)方式にした。これは以前ユーザーへ提案し合意を得た
「安全側(構造化フィルタ変換)」の設計そのもの。

データ取得元は demo-legacy-system が既に公開している読み取り専用JSON API
(GET /api/{entity}/list) のみで、レガシー側に一切の変更・追加エンドポイントを
要求しない(レガシー側は本機能の存在を知らない)。
"""
import json
import re

from app.config import Settings
from app.services import legacy_client
from app.services.ai_client import AiProvider

ALLOWED_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"}
_MAX_ROWS_FETCHED = legacy_client.MAX_ROWS_FETCHED  # プロンプト肥大化/レイテンシ防止の上限
_MAX_SAMPLE_ROWS = 3


class NLSQLService:
    def __init__(self, settings: Settings, ai: AiProvider):
        self.settings = settings
        self.ai = ai

    # ---------------------------------------------------------------
    # 1. レガシー側から対象エンティティの実データを取得(読み取り専用API)
    # ---------------------------------------------------------------
    async def _fetch_rows(self, entity: str) -> tuple[list[dict], str]:
        return await legacy_client.fetch_rows(self.settings, entity)

    # ---------------------------------------------------------------
    # 1.5 低カーディナリティな文字列項目(ステータス/区分等)の実際の値一覧を集計する。
    #     サンプル(先頭数件)だけでは該当ステータスが出現しないことがあり、AIが
    #     質問文の言葉(例:「出荷済」)を翻訳・意訳した値(例: "shipped")を
    #     でっち上げてしまい、eq比較が0件になる不具合があったため、実データから
    #     拾える「本物の語彙」を別途プロンプトに渡して選ばせるようにしている。
    # ---------------------------------------------------------------
    @staticmethod
    def _field_value_hints(rows: list[dict], max_distinct: int = 8) -> dict:
        hints: dict[str, list[str]] = {}
        if not rows:
            return hints
        sample_size = min(len(rows), _MAX_ROWS_FETCHED)
        for field in rows[0].keys():
            values = set()
            is_short_string_field = True
            for row in rows[:sample_size]:
                v = row.get(field)
                if v is None:
                    continue
                if not isinstance(v, str) or len(v) > 20:
                    is_short_string_field = False
                    break
                values.add(v)
                if len(values) > max_distinct:
                    break
            if is_short_string_field and 0 < len(values) <= max_distinct:
                hints[field] = sorted(values)
        return hints

    # ---------------------------------------------------------------
    # 2. AIへの指示プロンプト組み立て(実データのフィールド名+サンプル値のみ渡す。
    #    生SQL/コード実行を指示する文言は一切含めない)
    # ---------------------------------------------------------------
    @staticmethod
    def _build_prompt(label: str, question: str, fields: list[str], sample: list[dict], value_hints: dict) -> str:
        sample_json = json.dumps(sample, ensure_ascii=False, default=str)
        hints_json = json.dumps(value_hints, ensure_ascii=False)
        return (
            f"あなたはデータ検索アシスタントです。対象は基幹システムの「{label}」データ"
            f"(項目: {', '.join(fields)})です。サンプルレコード(先頭{len(sample)}件): {sample_json}\n\n"
            f"項目ごとに実際に使われている値の一覧(ステータス/区分等の判定に使うこと): {hints_json}\n\n"
            f"ユーザーの質問:「{question}」\n\n"
            "この質問を満たす絞り込み条件を、以下のJSON形式のみで出力してください"
            "(説明文・コードブロック記法・SQL文は一切不要。JSON以外の文字は出力しないこと):\n"
            '{"conditions": [{"field": "項目名", "op": "eq|ne|gt|gte|lt|lte|contains|in", "value": 値}],'
            ' "logic": "and|or", "sort": {"field": "項目名", "dir": "asc|desc"} または null,'
            ' "limit": 整数(既定50, 最大200)}\n'
            "fieldには上記項目名以外を使わないこと。質問に条件が明示されていなければ"
            "conditionsは空配列にすること。\n"
            "重要: 文字列のvalueは必ずサンプルレコードに実際に出現する表記をそのまま使うこと"
            "(例: ステータスや区分などの値は日本語のまま使い、英語へ翻訳・意訳・言い換えを"
            "しないこと。サンプルに完全一致する値が見当たらない場合や曖昧な場合は、"
            "opをeqではなくcontainsにして部分一致で照合すること)。"
        )

    # ---------------------------------------------------------------
    # 3. AI応答からJSON部分だけを取り出す(コードフェンスや前後の説明文に耐える)
    # ---------------------------------------------------------------
    @staticmethod
    def _extract_json(text: str) -> dict:
        if not text:
            return {}
        cleaned = re.sub(r"```(?:json)?", "", text).strip()
        match = re.search(r"\{.*\}", cleaned, re.DOTALL)
        if not match:
            return {}
        try:
            parsed = json.loads(match.group(0))
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}

    # ---------------------------------------------------------------
    # 4. ホワイトリスト検証(ここを通過した条件だけが実際に評価される)
    # ---------------------------------------------------------------
    @staticmethod
    def _validate_filter(raw: dict, fields: set[str]) -> tuple[dict, list[str]]:
        warnings: list[str] = []
        conditions = []
        for c in raw.get("conditions") or []:
            if not isinstance(c, dict):
                continue
            field, op, value = c.get("field"), c.get("op"), c.get("value")
            if field not in fields:
                warnings.append(f"未知の項目 '{field}' を含む条件は無視しました")
                continue
            if op not in ALLOWED_OPS:
                warnings.append(f"未対応の演算子 '{op}' を含む条件は無視しました")
                continue
            conditions.append({"field": field, "op": op, "value": value})

        logic = raw.get("logic") if raw.get("logic") in ("and", "or") else "and"

        sort = raw.get("sort") if isinstance(raw.get("sort"), dict) else None
        if sort and sort.get("field") not in fields:
            warnings.append(f"並び替え項目 '{sort.get('field')}' は無視しました")
            sort = None
        if sort:
            sort = {"field": sort["field"], "dir": "desc" if sort.get("dir") == "desc" else "asc"}

        limit = raw.get("limit")
        if not isinstance(limit, int) or limit <= 0 or limit > 200:
            limit = 50

        return {"conditions": conditions, "logic": logic, "sort": sort, "limit": limit}, warnings

    # ---------------------------------------------------------------
    # 5. 検証済み条件のみを安全に評価(eval不使用)
    # ---------------------------------------------------------------
    @staticmethod
    def _coerce_pair(actual, value):
        """可能なら数値同士で比較、無理なら文字列同士で比較する。"""
        try:
            return float(actual), float(value)
        except (TypeError, ValueError):
            return str(actual), str(value)

    @classmethod
    def _match(cls, row: dict, cond: dict) -> bool:
        field, op, value = cond["field"], cond["op"], cond["value"]
        actual = row.get(field)
        if actual is None:
            return False
        try:
            if op == "eq":
                return str(actual).lower() == str(value).lower()
            if op == "ne":
                return str(actual).lower() != str(value).lower()
            if op == "contains":
                return str(value).lower() in str(actual).lower()
            if op == "in":
                values = value if isinstance(value, list) else [value]
                return str(actual).lower() in {str(v).lower() for v in values}
            if op in ("gt", "gte", "lt", "lte"):
                a, v = cls._coerce_pair(actual, value)
                if op == "gt":
                    return a > v
                if op == "gte":
                    return a >= v
                if op == "lt":
                    return a < v
                if op == "lte":
                    return a <= v
        except (TypeError, ValueError):
            return False
        return False

    @classmethod
    def _apply_filter(cls, rows: list[dict], flt: dict) -> list[dict]:
        conditions = flt["conditions"]
        if conditions:
            if flt["logic"] == "or":
                rows = [r for r in rows if any(cls._match(r, c) for c in conditions)]
            else:
                rows = [r for r in rows if all(cls._match(r, c) for c in conditions)]
        if flt["sort"]:
            field = flt["sort"]["field"]
            reverse = flt["sort"]["dir"] == "desc"

            def sort_key(r):
                v = r.get(field)
                try:
                    return (0, float(v))
                except (TypeError, ValueError):
                    return (1, str(v))

            rows = sorted(rows, key=sort_key, reverse=reverse)
        return rows[: flt["limit"]]

    # ---------------------------------------------------------------
    # エントリーポイント
    # ---------------------------------------------------------------
    async def query(self, entity: str, question: str) -> dict:
        rows, label = await self._fetch_rows(entity)
        fields = set(rows[0].keys()) if rows else set()

        if not rows:
            return {
                "entity": entity, "label": label, "question": question,
                "applied_filter": {"conditions": [], "logic": "and", "sort": None, "limit": 50},
                "warnings": ["対象データが空のため検索できません"],
                "total_scanned": 0, "count": 0, "rows": [], "provider": self.ai.name,
            }

        value_hints = self._field_value_hints(rows)
        prompt = self._build_prompt(label, question, sorted(fields), rows[:_MAX_SAMPLE_ROWS], value_hints)
        ai_text = await self.ai.complete(prompt)
        raw = self._extract_json(ai_text)
        warnings = []
        if not raw:
            warnings.append("AI応答から条件を解釈できなかったため、絞り込みなしで返します")
        flt, filter_warnings = self._validate_filter(raw, fields)
        warnings.extend(filter_warnings)

        result_rows = self._apply_filter(rows, flt)
        return {
            "entity": entity, "label": label, "question": question,
            "applied_filter": flt, "warnings": warnings,
            "total_scanned": len(rows), "count": len(result_rows), "rows": result_rows,
            "provider": self.ai.name,
        }
