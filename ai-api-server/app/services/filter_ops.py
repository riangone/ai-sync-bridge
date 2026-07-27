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
