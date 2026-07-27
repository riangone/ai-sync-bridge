"""
AI応答からJSON部分だけを安全に取り出す共通ユーティリティ
==========================================================
nlsql_service(単一エンティティの構造化フィルタ生成)と dynamic_analysis_service
(クロス分析パラメータ生成)の両方が「AIにJSON以外の説明文・コードブロック記法を
出力させない」プロンプトを使うが、実際の応答には前後に説明文やコードフェンスが
混ざることがあるため、その耐性処理をここに一本化した(元は nlsql_service._extract_json
に閉じていた)。
"""
import json
import re


def extract_json(text: str) -> dict:
    """テキスト中から最初に現れる {...} ブロックをJSONとして取り出す。
    見つからない/パース失敗の場合は空dictを返す(呼び出し側で「解釈できなかった」
    扱いとして警告を出す設計)。"""
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
