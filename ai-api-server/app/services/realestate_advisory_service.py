"""
不動産仲介(instance="realestate")専用アドバイザリーサービス (Scoped)
=================================================================
erp/dealer には存在しない Property(物件)/Viewing(内見予約)エンティティに依存する
3機能をここにまとめる。erp/dealer に無理に共通化せず、deps.get_realestate_advisory_service
で instance != "realestate" を 404 にする(get_property_search_service の dealer 除外と
同じパターン)。

  - valuation():          査定AI。他2 demo には「資産の値付け」という業務概念自体が
    無いため、この3 demo の中で唯一 realestate だけが持てる機能。
  - commission_check():   宅建業法(宅地建物取引業法46条・国交省告示)の速算式による
    仲介手数料上限チェック。
  - viewing_conflicts():  内見の日程重複/エージェント過密検知。

cross_analysis_service.py / ar_ap_service.py と同じ設計方針を踏襲する:
  - 集計・判定ロジックは外部AIを一切呼ばない(閾値比較・統計量のみ)。AIプロバイダ
    未設定の環境でも本体機能は常に使える。
  - データ取得元は demo-legacy-system-realestate の読み取り専用API (/api/{entity}/list)
    のみ(legacy_client経由。nlsql_service/cross_analysis_serviceと共有し、レガシー側は
    AI-Sync Bridgeの存在を一切知らない)。
  - AIの解釈が欲しい場合は insight_service 経由のオプトイン `/insight` を使う
    (valuation/commission_checkのみ。viewing_conflictsは inventory_service.anomalies()に
    insightが無いのと同じ理由——単なる重複日程の列挙にAI解釈を挟む必要性が薄い——で
    提供しない)。
"""
from collections import defaultdict
from datetime import datetime
from statistics import median

from app.config import Settings
from app.services import legacy_client

_EXCLUDED_VIEWING_STATUSES = {"キャンセル"}
_AGENT_OVERLOAD_THRESHOLD = 3  # 同一エージェントが同日に担当する内見件数の過密しきい値


def _to_float(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        return f
    except (TypeError, ValueError):
        return default


class RealestateAdvisoryService:
    def __init__(self, settings: Settings):
        self.settings = settings

    # ---- 1. 査定AI(比較対象物件の㎡単価統計による想定成約価格帯の算出) ----
    async def valuation(
        self,
        property_type: str | None,
        building_area: float | None,
        land_area: float | None,
        address_keyword: str | None,
    ) -> dict:
        rows, _ = await legacy_client.fetch_rows(self.settings, "Property")
        target_area = building_area or land_area or 0.0

        def comparables(strict: bool) -> list[dict]:
            out = []
            for r in rows:
                area = _to_float(r.get("BuildingArea")) or _to_float(r.get("LandArea"))
                price = _to_float(r.get("Price"))
                if price <= 0 or area <= 0:
                    continue
                if strict and property_type and r.get("PropertyType") != property_type:
                    continue
                if strict and address_keyword and address_keyword not in (r.get("Address") or ""):
                    continue
                out.append({**r, "_unit_price": price / area})
            return out

        warnings: list[str] = []
        comps = comparables(strict=True)
        if len(comps) < 2:
            comps = comparables(strict=False)
            if comps:
                warnings.append("同条件(種別・エリア)の類似物件が不足していたため、全物件データから算出した参考値です。")

        if not comps or target_area <= 0:
            return {
                "generated_at": datetime.utcnow(),
                "comparable_count": len(comps),
                "unit_price_low": 0.0,
                "unit_price_median": 0.0,
                "unit_price_high": 0.0,
                "suggested_price_low": 0.0,
                "suggested_price_high": 0.0,
                "comparables": [],
                "summary": "査定対象の面積、または比較可能な物件データが不足しているため算出できません。",
                "warnings": warnings + (["面積(building_area/land_area)を指定してください。"] if target_area <= 0 else ["比較可能な物件データがありません。"]),
            }

        unit_prices = sorted(c["_unit_price"] for c in comps)
        n = len(unit_prices)
        med = median(unit_prices)
        # 四分位(件数が少ない場合は最小/最大にフォールバック)
        low = unit_prices[max(0, (n * 1) // 4)] if n >= 4 else unit_prices[0]
        high = unit_prices[min(n - 1, (n * 3) // 4)] if n >= 4 else unit_prices[-1]

        top_comps = sorted(comps, key=lambda c: abs(c["_unit_price"] - med))[:5]

        return {
            "generated_at": datetime.utcnow(),
            "comparable_count": len(comps),
            "unit_price_low": round(low, 1),
            "unit_price_median": round(med, 1),
            "unit_price_high": round(high, 1),
            "suggested_price_low": round(low * target_area),
            "suggested_price_high": round(high * target_area),
            "comparables": [
                {
                    "id": c.get("Id"),
                    "name": c.get("Name"),
                    "address": c.get("Address"),
                    "price": _to_float(c.get("Price")),
                    "unit_price": round(c["_unit_price"], 1),
                    "status": c.get("Status"),
                }
                for c in top_comps
            ],
            "summary": self._valuation_summary(len(comps), low, med, high, target_area),
            "warnings": warnings,
        }

    @staticmethod
    def _valuation_summary(n: int, low: float, med: float, high: float, area: float) -> str:
        return (
            f"類似物件{n}件の㎡単価(中央値{med:,.1f}円/㎡)から、対象物件(面積{area:,.1f}㎡)の"
            f"想定成約価格帯は{round(low * area):,}円〜{round(high * area):,}円です"
            "(統計的な参考値であり、AIによる査定判断ではありません)。"
        )

    # ---- 2. 宅建業法 仲介手数料上限チェック(速算式) ----
    def commission_check(self, contract_amount: float, requested_amount: float | None) -> dict:
        cap_excl_tax = self._legal_cap(contract_amount)
        cap_incl_tax = round(cap_excl_tax * 1.10)
        requested = requested_amount if requested_amount is not None else float(cap_incl_tax)
        over = requested > cap_incl_tax
        return {
            "contract_amount": contract_amount,
            "legal_cap_excl_tax": round(cap_excl_tax),
            "legal_cap_incl_tax": cap_incl_tax,
            "requested_amount": requested,
            "over_legal_cap": over,
            "diff": round(requested - cap_incl_tax),
            "summary": self._commission_summary(contract_amount, cap_incl_tax, requested, over),
        }

    @staticmethod
    def _legal_cap(amount: float) -> float:
        # 宅地建物取引業法46条 + 告示による報酬額の速算式(片手・税抜)。
        if amount <= 2_000_000:
            return amount * 0.05
        if amount <= 4_000_000:
            return amount * 0.04 + 20_000
        return amount * 0.03 + 60_000

    @staticmethod
    def _commission_summary(amount: float, cap_incl_tax: float, requested: float, over: bool) -> str:
        base = f"契約金額{amount:,.0f}円における宅建業法上の仲介手数料上限(税込)は{cap_incl_tax:,.0f}円です。"
        if over:
            return base + f" 請求予定額{requested:,.0f}円は上限を{requested - cap_incl_tax:,.0f}円超過しています(法令違反のおそれ)。"
        return base + f" 請求予定額{requested:,.0f}円は上限内です。"

    # ---- 3. 内見(Viewing)日程重複/エージェント過密検知(inventory anomaliesと同じくルールベースのみ) ----
    async def viewing_conflicts(self) -> dict:
        rows, _ = await legacy_client.fetch_rows(self.settings, "Viewing")
        active = [r for r in rows if r.get("Status") not in _EXCLUDED_VIEWING_STATUSES and r.get("ViewingDate")]

        by_property_date: dict[tuple, list[dict]] = defaultdict(list)
        by_agent_date: dict[tuple, list[dict]] = defaultdict(list)
        for r in active:
            by_property_date[(r.get("PropertyId"), r.get("ViewingDate"))].append(r)
            if r.get("EmployeeId"):
                by_agent_date[(r.get("EmployeeId"), r.get("ViewingDate"))].append(r)

        conflicts: list[dict] = []
        for (pid, date), items in by_property_date.items():
            if len(items) < 2:
                continue
            conflicts.append({
                "type": "property_double_booking",
                "severity": "high",
                "date": date,
                "property_id": pid,
                "property_name": items[0].get("PropertyName"),
                "employee_id": None,
                "viewing_ids": [i.get("Id") for i in items],
                "message": f"{items[0].get('PropertyName') or '物件'}が{date}に{len(items)}件重複して内見予約されています。",
            })

        for (eid, date), items in by_agent_date.items():
            if len(items) < _AGENT_OVERLOAD_THRESHOLD:
                continue
            conflicts.append({
                "type": "agent_overload",
                "severity": "medium",
                "date": date,
                "property_id": None,
                "property_name": None,
                "employee_id": eid,
                "viewing_ids": [i.get("Id") for i in items],
                "message": f"{items[0].get('EmployeeName') or ('担当者ID:' + str(eid))}が{date}に{len(items)}件の内見を担当しており過密です。",
            })

        conflicts.sort(key=lambda c: ({"high": 0, "medium": 1}.get(c["severity"], 2), c["date"]))
        high_count = sum(1 for c in conflicts if c["severity"] == "high")
        return {
            "generated_at": datetime.utcnow(),
            "conflicts": conflicts,
            "total_conflicts": len(conflicts),
            "high_count": high_count,
            "summary": self._conflict_summary(conflicts, high_count),
        }

    @staticmethod
    def _conflict_summary(conflicts: list[dict], high_count: int) -> str:
        if not conflicts:
            return "内見予約の日程重複・エージェント過密はありません。"
        return f"内見予約に{len(conflicts)}件の注意事項があります(物件の二重案内{high_count}件を含む)。優先して調整してください。"
