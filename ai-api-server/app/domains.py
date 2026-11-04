"""
ルーター登録の「コア / 業種ドメイン」境界。

  CORE_ROUTERS   … 業種非依存の製品本体。常に有効。
  DOMAIN_ROUTERS … 特定業種・特定デモのための機能。AISB_DOMAINS で選択する。
                   ("all"=全部[既定・従来互換]、""=コアのみ、"erp_sales,realestate" 等)

新しい業種機能を追加するときはコアに足さず、ここにドメインとして登録すること。
(将来的には app/domains/<name>/ パッケージへ物理移動する。現時点は登録境界のみ。)
"""
from __future__ import annotations

from fastapi import APIRouter, FastAPI

from app.routers import (
    admin,
    analysis_history,
    analytics,
    ar_ap,
    bridge,
    bridge_demo,
    chat,
    conversational_input,
    cross_analysis,
    customers,
    inventory,
    local_ai,
    nlsql,
    notifications,
    ocr,
    orders,
    profit_report,
    purchase_order,
    push,
    realestate,
    recommend,
    search,
    web_search,
    workflows,
)

CORE_ROUTERS: list[APIRouter] = [
    bridge.router,
    bridge_demo.router,
    chat.router,
    ocr.router,
    search.router,
    nlsql.router,
    cross_analysis.router,
    analytics.router,
    analysis_history.router,
    workflows.router,
    notifications.router,
    push.router,
    admin.router,
    recommend.router,
    web_search.router,
    local_ai.router,
    conversational_input.router,
]

DOMAIN_ROUTERS: dict[str, list[APIRouter]] = {
    # 販売管理/ERP系デモ(DemoDataStore ベースの顧客・受注・在庫・発注・利益・売掛買掛)
    "erp_sales": [
        customers.router,
        orders.router,
        inventory.router,
        purchase_order.router,
        profit_report.router,
        ar_ap.router,
    ],
    # 不動産仲介(査定/内見重複/仲介手数料)。deps 側でも instance != realestate は404にしている
    "realestate": [realestate.router],
}


def resolve_domains(spec: str) -> list[str]:
    spec = (spec or "").strip()
    if spec == "all":
        return list(DOMAIN_ROUTERS)
    names = [s.strip() for s in spec.split(",") if s.strip()]
    unknown = [n for n in names if n not in DOMAIN_ROUTERS]
    if unknown:
        raise ValueError(f"unknown AISB_DOMAINS: {unknown} (available: {list(DOMAIN_ROUTERS)})")
    return names


def register_routers(app: FastAPI, domain_spec: str) -> list[str]:
    for r in CORE_ROUTERS:
        app.include_router(r)
    enabled = resolve_domains(domain_spec)
    for name in enabled:
        for r in DOMAIN_ROUTERS[name]:
            app.include_router(r)
    return enabled
