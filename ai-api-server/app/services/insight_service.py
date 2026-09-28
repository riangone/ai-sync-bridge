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
- 生成失敗(プロバイダエラー)はここで揉み消さず素通しする。AiProvider.complete() は失敗時に
  文字列ではなく AIProviderError を送出する設計(ai_client.py参照、旧実装は
  "[xxx-error-fallback] ..." という文字列を正常応答と区別なくreturnしていたため、
  interpret_* の呼び出し元(analytics/recommend/purchase_order等の各routerの
  `/insight` 系サブエンドポイント)がその文字列をそのまま「AIの解釈コメント」として
  ユーザーに表示してしまうサイレント破損があった)。ここでは意図的にtry/exceptを
  書かず伝播させ、app.main の AIProviderError 用 exception_handler が一律502の
  構造化エラーに変換する。本体の統計・一覧データは `/insight` とは別の独立した
  エンドポイントで提供されるため(routerのコメント参照)、この502はAIコメントの
  取得失敗のみを意味し、本体機能には影響しない。
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


async def interpret_valuation(ai: AiProvider, valuation_result: dict) -> str:
    """realestate_advisory_service.RealestateAdvisoryService.valuation() の出力
    (類似物件の㎡単価統計から算出した想定成約価格帯)をAIに解釈させる。instance=="realestate"
    専用。他demoには「資産の値付け」という業務概念自体が無いため対応する report は無い。"""
    if not valuation_result.get("comparable_count"):
        return "比較可能な類似物件データが無いため、解釈できません。"
    comps = valuation_result.get("comparables", [])
    lines = [
        f"{c.get('name')}({c.get('address')}): 価格={c.get('price', 0):,.0f}円, "
        f"㎡単価={c.get('unit_price', 0):,.1f}円/㎡, ステータス={c.get('status')}"
        for c in comps[:_MAX_ITEMS_IN_PROMPT]
    ]
    prompt = (
        f"以下は類似物件{valuation_result['comparable_count']}件の㎡単価統計から算出した"
        f"想定成約価格帯です(㎡単価: 下限={valuation_result['unit_price_low']:,.1f}円, "
        f"中央値={valuation_result['unit_price_median']:,.1f}円, "
        f"上限={valuation_result['unit_price_high']:,.1f}円。統計計算の結果であり、AIの査定"
        "判断ではありません)。\n"
        f"想定成約価格帯: {valuation_result['suggested_price_low']:,.0f}円〜"
        f"{valuation_result['suggested_price_high']:,.0f}円\n"
        "参考にした類似物件:\n" + "\n".join(lines) + "\n\n"
        "査定担当のエージェント向けに、この価格帯の妥当性・売主への説明時に注意すべき点を"
        "日本語で3〜4行程度でまとめてください。"
    )
    return await ai.complete(prompt)


async def interpret_commission_check(ai: AiProvider, check_result: dict) -> str:
    """realestate_advisory_service.RealestateAdvisoryService.commission_check() の出力
    (宅建業法の速算式による仲介手数料上限チェック)をAIに解釈させる。instance=="realestate"専用。"""
    prompt = (
        f"契約金額{check_result['contract_amount']:,.0f}円に対する宅建業法上の仲介手数料"
        f"上限(税込)は{check_result['legal_cap_incl_tax']:,.0f}円、請求予定額は"
        f"{check_result['requested_amount']:,.0f}円です"
        f"(超過={'はい' if check_result['over_legal_cap'] else 'いいえ'}、"
        "速算式によるルールベース判定であり、AIの判断ではありません)。\n"
        "宅建士向けに、法令上のリスクと顧客への説明時に留意すべき点を"
        "日本語で2〜3行程度でまとめてください。"
    )
    return await ai.complete(prompt)
