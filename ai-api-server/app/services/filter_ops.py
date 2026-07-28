"""
AI生成フィルタ条件の共通評価ロジック
======================================
nlsql_service(単一エンティティ)と dynamic_analysis_service(クロス分析、複数
エンティティ)の両方が「AIにはフィルタ条件のフィールド名/演算子/値だけをJSONで
生成させ、ホワイトリスト検証を通過した条件のみをコード側で評価する(evalも生SQLも
使わない)」という同一方式を採るため、演算子の評価ロジックをここに一本化した
(元は nlsql_service._match/_coerce_pair に閉じていた)。
"""

ALLOWED_OPS = {"eq", "ne", "gt", "gte", "lt", "lte", "contains", "in"}


def coerce_pair(actual, value):
    """可能なら数値同士で比較、無理なら文字列同士で比較する。"""
    try:
        return float(actual), float(value)
    except (TypeError, ValueError):
        return str(actual), str(value)


def match_value(actual, op: str, value) -> bool:
    """opはALLOWED_OPSでホワイトリスト検証済みであること前提。actualがNoneの場合は
    (フィールド欠損として)常に不一致扱いにする。"""
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
            a, v = coerce_pair(actual, value)
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


# ---------------------------------------------------------------------------
# 表示専用の疑似SQL断片組み立て(実行はしない)
# ---------------------------------------------------------------------------
# ユーザーから「AIが生成・実行したSQLも見たい」という要望があったが、本システムには
# そもそも実SQLエンジンが存在しない(データ層はdemo-legacy-system側のインメモリdict、
# AIが生成するのは上記のホワイトリスト検証済み構造化フィルタのみ)。実行しているものを
# 見せることはできないため、代わりに「検証済みのfield/op/valueから、人間が読みやすい
# SQL風の文字列を機械的に組み立てて表示する」透明性目的のプレビューを提供する。
# 組み立てに使うのは検証・型チェック済みの値のみで、AIの生テキストを直接文字列結合
# することはない(値は _sql_literal で必ずクォート/エスケープする)ため、
# この文字列自体が何かに対して実行されることもなく、注入の懸念もない。
_SQL_OP = {"eq": "=", "ne": "<>", "gt": ">", "gte": ">=", "lt": "<", "lte": "<="}


def _sql_literal(value) -> str:
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "(" + ", ".join(_sql_literal(v) for v in value) + ")"
    return "'" + str(value).replace("'", "''") + "'"


def render_condition_sql(field: str, op: str, value) -> str:
    """表示専用。実際の絞り込みはmatch_value()が担い、この文字列は何も実行しない。"""
    if op == "contains":
        return f"{field} LIKE '%{str(value).replace(chr(39), chr(39) * 2)}%'"
    if op == "in":
        return f"{field} IN {_sql_literal(value)}"
    return f"{field} {_SQL_OP.get(op, '=')} {_sql_literal(value)}"
