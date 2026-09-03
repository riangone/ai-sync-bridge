"""
AI Insight Service (Scoped/Stateless)
実装ロードマップ Phase3拡張: 統計/ルールベースの各機能(予測分析・ワークフロー・管理統計・
類似レコード推薦・発注提案・AR/APエイジング・粗利レポート・アラート集約)が算出した「数字」を
AiProvider に渡し、トレンドの解釈コメントを自然言語で生成させる薄いアダプタ層。

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
        return "実行されたワークフローがまだないため、傾向を解釈できません。"
    lines = [
        f"{h['workflow_name']}: status={h['status']} "
        f"({sum(1 for s in h['steps'] if s['status'] == 'success')}/{len(h['steps'])}ステップ成功)"
        for h in history[:_MAX_ITEMS_IN_PROMPT]
    ]
    prompt = (
        "以下はワークフローエンジンが実行した最近のワークフロー一覧です"
        "(各ステップの条件式・アクション実行の結果であり、AIの判断ではありません)。\n"
        "傾向・繰り返し失敗しているワークフロー・優先対応すべき事項を日本語で3〜4行程度でまとめてください。\n"
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


async def interpret_recommend(ai: AiProvider, recommend_result: dict) -> str:
    """recommend_service.RecommendService.recommend() の出力(文字bi-gram類似度による
    ルールベースの結果)をAIに解釈させる。既存の explanation(一致フィールドの機械的な
    文章化)とは別物であることをプロンプトで明記し、AIには「なぜ業務上関連しそうか」
    という一段上の解釈を求める。"""
    table_name = recommend_result.get("table_name", "")
    results = recommend_result.get("results", [])
    if not results:
        return "類似度が0より大きいレコードがなかったため、解釈できません。"
    lines = [
        f"id={r['id']}: 類似度={r['score']}, 内容={r['text']}"
        for r in results[:_MAX_ITEMS_IN_PROMPT]
    ]
    prompt = (
        f"以下は「{table_name}」テーブルの中から、文字列の類似度(bi-gram Jaccard係数、"
        "AIの判断ではなく機械的な計算です)が高い順に抽出したレコード一覧です。\n"
        "業務担当者向けに、これらのレコードがなぜ業務上関連していそうか、"
        "注目すべき共通点があれば日本語で2〜3行程度でまとめてください。\n" + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_purchase_proposal(ai: AiProvider, proposal_result: dict) -> str:
    """purchase_order_service.PurchaseOrderService.propose() の出力(reorder_point割れ量
    から算出したルールベースの発注提案)をAIに解釈させる。"""
    proposals = proposal_result.get("proposals", [])
    if not proposals:
        return "発注点を下回っている商品がないため、解釈できません。"
    lines = [
        f"{p['product_name']}: 現在庫={p['current_stock']}, 発注点={p['reorder_point']}, "
        f"推奨発注数={p['suggested_qty']}, 仕入先={p['supplier']}"
        for p in proposals[:_MAX_ITEMS_IN_PROMPT]
    ]
    prompt = (
        f"以下は発注点(reorder_point)を下回った商品ごとの発注提案です(発注点*2-在庫数、"
        "という単純な計算式によるルールベースの提案であり、AIの判断ではありません)。\n"
        "業務担当者向けに、特に優先して発注すべき商品とその理由、"
        "注意点を日本語で3〜4行程度でまとめてください。\n" + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_aging(ai: AiProvider, aging_result: dict) -> str:
    """ar_ap_service.ArApService.aging() の出力(売掛/買掛エイジング集計)をAIに解釈させる。
    summary(ルールベースの定型コメント)とは別に、AIならではの一段深い着眼点を求める。"""
    rows = aging_result.get("aging_report", [])
    if not rows:
        return "売掛・買掛の対象データがないため、解釈できません。"
    lines = [
        f"{r['entity_name']}({'売掛' if r['entity_type'] == 'receivable' else '買掛'}): "
        f"合計={r['total']:,.0f}円, 90日超滞留={r['bucket_90_plus']:,.0f}円, リスク={r['risk']}"
        for r in rows[:_MAX_ITEMS_IN_PROMPT]
    ]
    prompt = (
        f"以下は売掛金/買掛金のエイジング集計です(売掛合計={aging_result.get('total_receivable', 0):,.0f}円, "
        f"買掛合計={aging_result.get('total_payable', 0):,.0f}円。滞留日数の閾値判定によるルールベースの"
        "集計であり、AIの判断ではありません)。\n"
        "業務担当者向けに、資金繰り上特に注意すべき先・優先して対応すべき順序を"
        "日本語で3〜4行程度でまとめてください。\n" + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_profit_report(ai: AiProvider, report_result: dict) -> str:
    """profit_report_service.ProfitReportService.report() の出力(商品別売上/原価/粗利)を
    AIに解釈させる。"""
    details = report_result.get("product_details", [])
    if not details:
        return "対象期間の受注データがないため、解釈できません。"
    lines = [
        f"{d['product_name']}: 売上={d['revenue']:,.0f}円, 粗利={d['profit']:,.0f}円, "
        f"粗利率={d['margin_rate'] * 100:.1f}%"
        f"{'(原価未登録)' if not d['cost_known'] else ''}"
        for d in details[:_MAX_ITEMS_IN_PROMPT]
    ]
    prompt = (
        f"以下は商品別の売上/原価/粗利レポートです(総粗利={report_result.get('total_profit', 0):,.0f}円。"
        "商品マスタとの突き合わせによる集計であり、AIの判断ではありません)。\n"
        "業務担当者向けに、収益性の観点で注目すべき商品・改善のヒントを"
        "日本語で3〜4行程度でまとめてください。\n" + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_alerts(ai: AiProvider, alerts_result: dict) -> str:
    """push_service.PushService.check() の出力(在庫異常+AR/AP高リスクの集約アラート)を
    AIに解釈させる。"""
    alerts = alerts_result.get("alerts", [])
    if not alerts:
        return "現在、対応が必要なアラートがないため、解釈できません。"
    lines = [f"[{a['severity']}] {a['title']}: {a['message']}" for a in alerts[:_MAX_ITEMS_IN_PROMPT]]
    prompt = (
        f"以下は在庫異常・売掛/買掛の高リスク滞留を集約したアラート一覧です"
        f"(緊急={alerts_result.get('high_count', 0)}件, 注意={alerts_result.get('medium_count', 0)}件。"
        "既存の閾値判定ロジックの出力であり、AIの判断ではありません)。\n"
        "業務担当者向けに、対応の優先順位と理由を日本語で3〜4行程度でまとめてください。\n"
        + "\n".join(lines)
    )
    return await ai.complete(prompt)


async def interpret_admin_stats(ai: AiProvider, stats: dict) -> str:
    prompt = (
        "以下はシステムの現在の統計情報です。運用者向けに、注目すべき点があれば"
        "日本語で2〜3行程度のコメントを返してください(特筆すべき点がなければ"
        "「特に問題ありません」で構いません)。\n"
        f"顧客数={stats['customer_count']}, 受注数={stats['order_count']}, "
        f"ワークフロー定義数={stats['workflow_count']}, "
        f"実行回数={stats['workflow_execution_count']}, "
        f"未読通知数={stats['unread_notification_count']}, "
        f"AIプロバイダ={stats['ai_provider']}, デモモード={stats['demo_mode']}"
    )
    return await ai.complete(prompt)
