"""
AI Insight Service (Scoped/Stateless)
実装ロードマップ Phase3拡張: 統計/ルールベースの各機能(予測分析・ワークフロー・管理統計)が
算出した「数字」を AiProvider に渡し、トレンドの解釈コメントを自然言語で生成させる薄い
アダプタ層。

設計方針:
- predictive_service / workflow_service / admin_service 自体は既存方針通り AI 非依存の
  ままにする(AIプロバイダ未設定でも本体機能(数値・一覧)は常に使えるという既存コメントの
  方針を壊さない)。このモジュールは完全にオプトインの追加レイヤーとして分離した。
- プロンプトは生JSONを丸投げせず、要点を先に日本語で箇条書き整形してから渡す
  (トークン節約とモデルの解釈精度向上が目的)。
- どの統計も「これはAIの判断ではなく統計/ルール評価の結果である」旨をプロンプトに明記し、
  AIの解釈コメントと機械的な計算結果が混同されないようにしている。
- 生成失敗(プロバイダエラー)はここで揉み消さず素通しする。各 AiProvider.complete() は
  例外を "[xxx-error-fallback] ..." という文字列に変換して返す設計(ai_client.py参照)なので、
  ここでも同じ文字列がそのまま comment に入る(既存のchat/summarize経路と同じ挙動に揃えた)。
"""
from app.services.ai_client import AiProvider

_MAX_ITEMS_IN_PROMPT = 15  # プロンプト肥大化防止の共通上限


async def interpret_forecast(ai: AiProvider, forecast: dict) -> str:
    points = forecast.get("points", [])
    if not points:
        return "受注データが不足しているため、トレンドを解釈できません。"
    lines = [f"{p['month']}: 実績={p['actual']}, 予測={p['predicted']}" for p in points]
    prompt = (
        "以下は月次売上の実績と、最小二乗法による線形回帰の予測値です"
        "(これはAIの判断ではなく統計計算の結果です)。\n"
        "業務担当者向けに、トレンドの方向性・注意点・次に取るべきアクション案を"
        "日本語で3〜4行程度にまとめてください。\n" + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_reorders(ai: AiProvider, predictions: dict) -> str:
    preds = predictions.get("predictions", [])
    if not preds:
        return "再受注リスクを推定できる発注履歴がありません。"
    overdue = [p for p in preds if p["risk"] == "overdue"]
    due_soon = [p for p in preds if p["risk"] == "due_soon"]
    lines = [
        f"{p['customer_name']}: リスク={p['risk']}, 次回予測={p['expected_next_date']}"
        f"({p['days_until_expected']}日)"
        for p in preds[:_MAX_ITEMS_IN_PROMPT]
    ]
    prompt = (
        f"以下は顧客ごとの再受注予測です(overdue={len(overdue)}件, due_soon={len(due_soon)}件、"
        "平均発注間隔法による統計推定であり、AIの判断ではありません)。\n"
        "特に優先してフォローすべき顧客とその理由を、日本語で3〜4行程度で挙げてください。\n"
        + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_workflow_history(ai: AiProvider, history: list) -> str:
    if not history:
        return "発火した自動化イベントがまだないため、傾向を解釈できません。"
    lines = [f"{h['rule_name']}: {h['message']}" for h in history[:_MAX_ITEMS_IN_PROMPT]]
    prompt = (
        "以下は業務ルールエンジンが発火させた最近のイベント一覧です"
        "(条件式ベースのルール評価であり、AIの判断ではありません)。\n"
        "傾向・繰り返し発生している問題・優先対応すべき事項を日本語で3〜4行程度でまとめてください。\n"
        + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_cross_analysis(ai: AiProvider, result: dict) -> str:
    """与信リスク/在庫逼迫/滞留債権など、cross_analysis_service の各レポート共通の
    解釈コメント生成。summary(集計値)とchart上位N件(既にランキング済み)だけを渡し、
    生のrows全件はプロンプトに含めない(トークン節約、かつ既にサーバー側で
    ソート・上位抽出済みのため十分)。"""
    label = result.get("label", "")
    summary = result.get("summary", {})
    chart = result.get("chart", {})
    categories = chart.get("categories", [])
    if not categories:
        return f"「{label}」に該当するデータがないため、傾向を解釈できません。"

    summary_line = ", ".join(f"{k}={v}" for k, v in summary.items())
    series_lines = []
    for s in chart.get("series", []):
        pairs = ", ".join(f"{c}={v}" for c, v in zip(categories, s.get("values", [])))
        series_lines.append(f"{s.get('label')}: {pairs}")

    prompt = (
        f"以下は基幹システムの「{label}」の集計結果です"
        "(複数の業務データを突き合わせた集計・閾値判定であり、AIの判断ではありません)。\n"
        f"概況: {summary_line}\n"
        f"上位項目の内訳:\n" + "\n".join(series_lines) + "\n\n"
        "業務担当者向けに、特に注意すべき先・原因として考えられる点・次に取るべき"
        "アクション案を日本語で3〜4行程度にまとめてください。"
    )
    return await ai.complete(prompt)


async def interpret_admin_stats(ai: AiProvider, stats: dict) -> str:
    prompt = (
        "以下はシステムの現在の統計情報です。運用者向けに、注目すべき点があれば"
        "日本語で2〜3行程度のコメントを返してください(特筆すべき点がなければ"
        "「特に問題ありません」で構いません)。\n"
        f"顧客数={stats['customer_count']}, 受注数={stats['order_count']}, "
        f"ワークフロールール数={stats['workflow_rule_count']}, "
        f"発火イベント数={stats['workflow_event_count']}, "
        f"未読通知数={stats['unread_notification_count']}, "
        f"AIプロバイダ={stats['ai_provider']}, デモモード={stats['demo_mode']}"
    )
    return await ai.complete(prompt)
