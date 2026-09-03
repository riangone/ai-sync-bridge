"""
normalize_util — 「様々な表記揺れを持つ入力dictを、レガシーフォームの正規フィールド名に
マッピングする」処理の共通実装(4.1章「類義語マップ」と同じ考え方の簡易版)。

元々 web_search_service.py にプライベート関数として実装されていたが、2026-08-31 に
OCR機能(ocr_service.py)からも同じロジックが必要になったため、共通ユーティリティとして
切り出した。両サービスとも「AI/外部データが返した緩いキー名の集合を、書き込み対象と
なるレガシーフォームの name 属性に正規化するだけの純粋関数」という役割は同一で、
DBアクセスは一切行わない(実際の書き込みはフロント側の auto-input-engine.openAndFill()
がユーザーの明示操作をきっかけに行う)。
"""


def normalize(data: dict, field_synonyms: dict[str, list[str]]) -> dict:
    """入力dictのキー(様々な表記揺れ)をレガシーフォームの正規フィールド名にマッピングする。
    一致するキーが無いフィールドは省略する(空文字で埋めて誤登録の温床にするより安全)。"""
    lower_data = {str(k).lower(): v for k, v in data.items() if v is not None}
    normalized: dict = {}
    for legacy_key, synonyms in field_synonyms.items():
        for candidate in (legacy_key, *synonyms):
            if candidate.lower() in lower_data:
                normalized[legacy_key] = lower_data[candidate.lower()]
                break
    return normalized
