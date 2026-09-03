"""
Web Search Service (Scoped): CompanySearchService / PropertySearchService
実装ロードマップ Phase2: README 5.3節「外部データ検索系」
(POST /api/company/search, /api/company/register, /api/property/search,
/api/property/register)、5.4.14「CompanySearchService / PropertySearchService」。

README 6.1章の設計原則(レガシーシステムは AI-Sync Bridge の存在を一切知らない、
読み取り専用 GET /api/{entity}/list 以外は一切公開しない)により、AI API サーバー
側からレガシーDBへ直接書き込むことは行わない。実際の登録(INSERT)は、Chrome拡張の
auto-input-engine が検索結果でレガシー画面(Customer/Entry, Property/Register)の
フォームフィールドを自動入力し、ユーザー自身がレガシー画面の保存ボタンを押すことで
完了する(4.2.2 content-script.js の画面種別検出ルール: company→customer-register,
Property or 物件→property-register)。

したがって register() は「レガシーフォームのフィールド名(demo-legacy-system の
CUSTOMER_FIELDS / PROPERTY_FIELDS)に正規化するだけの純粋関数」であり、DBアクセスが
一切無いため demo/prod で挙動を変える必要がない。

search() について(2026-08-20 改訂):
README は「OpenCode CLIのEXA検索またはGoogle Custom Search」を実Web検索の接続先候補
として挙げていたが、実機検証の結果 OpenCode CLI (`opencode serve`) 自体が `websearch`
という組み込みツールを持ち、エージェントループの中で自律的に実Web検索を実行し、実在
のURL・記事を返すことを確認済み(`/experimental/tool/ids` に `websearch` が列挙され、
実際に session/message 経由で今日の日付の実ニュースを取得できた)。したがって
「外部検索API契約が必要な未実装の拡張点」ではなく、AIプロバイダが opencode の場合は
即座に実検索が可能——ai_client.OpenCodeProvider を注入し、そちらを優先する。

優先順位:
  1. ai プロバイダが opencode -> _ai_search() で実際に websearch ツールを使わせ、
     構造化JSONで結果を受け取る(demo_mode の真偽に関わらず実行——Web検索能力の有無は
     「AI疎通性」の軸であって「レガシーDB接続性」の軸(demo_mode)とは別物、という
     assistant_service.py で採った判断と同じ考え方)。
  2. opencode 以外(mock/openai/gemini)かつ demo_mode=true -> 従来通り決定的な擬似結果
     (openai/geminiは素のchat completion APIのみでツール呼び出し非対応のため、現状は
     実検索に対応できない)。
  3. それ以外(prod かつ 非opencode) -> 引き続き NotImplementedError の拡張点として残す。
"""
import hashlib
import random

from app.services import ai_json_util
from app.services.ai_client import AiProvider
from app.services.normalize_util import normalize as _normalize


def _seed_from(*parts: str) -> int:
    digest = hashlib.sha256("|".join(parts).encode()).hexdigest()
    return int(digest, 16) % (2**32)


def _coerce_number(value, cast):
    """AIが返す数値項目は文字列("約500㎡"等)や単位混じりの場合があるため、
    素直にcastできない値は None にする(誤った数値を作り出すより安全)。"""
    if value is None:
        return None
    try:
        return cast(value)
    except (TypeError, ValueError):
        digits = "".join(ch for ch in str(value) if ch.isdigit() or ch == ".")
        try:
            return cast(float(digits)) if digits else None
        except (TypeError, ValueError):
            return None


class CompanySearchService:
    # 「実在する企業」を受け止めるレガシーフォームは instance によって異なる:
    #   - erp: demo-legacy-system の Customer フォーム(CUSTOMER_FIELDS)= 取引先企業そのもの。
    #   - dealer: demo-legacy-system-dealer の Supplier フォーム(SUPPLIER_FIELDS)=
    #     仕入先(オークション会場・下取り仲介業者)。dealer の Customer は氏名/運転免許証番号
    #     等の個人向け項目のみで、資本金/業種/従業員数といった法人項目が存在しないため、
    #     「企業を検索する」機能は Customer ではなく Supplier に正規化する方が実体に即す
    #     (2026-08-30 instance分岐導入。register_entity で panel-web-search.js 側の
    #     自動入力先フォームURLも合わせて切り替える)。
    FIELD_SYNONYMS_BY_INSTANCE: dict[str, dict[str, list[str]]] = {
        "erp": {
            "Name": ["name", "companyName", "company_name"],
            "NameKana": ["name_kana", "nameKana", "kana"],
            "Representative": ["representative", "ceo"],
            "PostalCode": ["postal_code", "postalCode", "zip"],
            "Address": ["address"],
            "Tel": ["tel", "phone"],
            "Fax": ["fax"],
            "Website": ["website", "url"],
            "Capital": ["capital"],
            "Employees": ["employees", "employee_count"],
            "Industry": ["industry"],
            "CreditLimit": ["credit_limit", "creditLimit"],
            "Notes": ["notes", "memo"],
        },
        # demo-legacy-system-dealer SUPPLIER_FIELDS に対応。
        "dealer": {
            "Name": ["name", "companyName", "company_name"],
            "Category": ["industry"],
            "Tel": ["tel", "phone"],
            "Address": ["address"],
            "ContactPerson": ["representative", "ceo"],
            "CreditAmount": ["capital"],
            "PaymentTerms": [],
            "Notes": ["notes", "memo"],
        },
    }
    _RESULT_KEYS = (
        "name", "name_kana", "representative", "address", "tel", "website",
        "industry", "capital", "employees",
    )
    _PROMPT_TEMPLATE = (
        "あなたはWeb検索ツール(websearch)を使って実在する企業を調査するアシスタントです。\n"
        "必ず websearch ツールで実際に検索を実行してから回答してください(検索せず記憶だけで"
        "答えることは禁止)。\n"
        "検索キーワード: {keyword}\n"
        "検索結果から、キーワードに関連しそうな実在の企業を最大3社ピックアップし、"
        "分かった情報のみをまとめてください。不明な項目は必ず null にし、推測で埋めないこと。\n"
        "出力は説明文・Markdown・コードフェンスを一切含めず、次のJSON形式のみを出力してください:\n"
        '{{"results": [{{"name": "string(必須)", "name_kana": "string|null", '
        '"representative": "string|null", "address": "string|null", "tel": "string|null", '
        '"website": "string|null", "industry": "string|null", "capital": "number|null", '
        '"employees": "number|null"}}]}}'
    )

    def __init__(self, demo_mode: bool = True, ai: AiProvider | None = None, instance: str = "erp"):
        self.demo_mode = demo_mode
        self.ai = ai
        self.field_synonyms = self.FIELD_SYNONYMS_BY_INSTANCE.get(
            instance, self.FIELD_SYNONYMS_BY_INSTANCE["erp"]
        )
        # panel-web-search.js が自動入力先フォームURLを組み立てる際に使う
        # (フロント側でinstanceからentity名を再導出しなくて済むよう、レスポンスに含める)。
        self.register_entity = "Supplier" if instance == "dealer" else "Customer"

    async def search(self, keyword: str) -> dict:
        if self.ai is not None and getattr(self.ai, "name", "") == "opencode":
            return await self._ai_search(keyword)
        if self.demo_mode:
            return {"keyword": keyword, "results": self._mock_search(keyword), "source": "mock"}
        raise NotImplementedError("実Web検索API(EXA検索/Google Custom Search等)を接続してください")

    async def _ai_search(self, keyword: str) -> dict:
        # tools明示指定(2026-08-21): モデルの自発的判断(プロンプト頼み)に任せず、
        # opencode側にwebsearchツールの利用を強制する。
        ai_text = await self.ai.complete(
            self._PROMPT_TEMPLATE.format(keyword=keyword), tools={"websearch": True}
        )
        if ai_text.startswith("[opencode-error-fallback]"):
            # 上流モデルエラー(401等)をここで検知できるようになった(旧実装は
            # サイレントに0件・source="opencode-websearch"を返していた)。
            return {"keyword": keyword, "results": [], "source": "opencode-error", "error": ai_text}
        parsed = ai_json_util.extract_json(ai_text)
        raw_results = parsed.get("results")
        results = []
        if isinstance(raw_results, list):
            for item in raw_results:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                cleaned = {k: item.get(k) for k in self._RESULT_KEYS}
                cleaned["capital"] = _coerce_number(cleaned["capital"], int)
                cleaned["employees"] = _coerce_number(cleaned["employees"], int)
                results.append(cleaned)
        return {"keyword": keyword, "results": results, "source": "opencode-websearch"}

    def register(self, company_data: dict) -> dict:
        """レガシーフォーム(instance="dealer"ならSupplier、それ以外はCustomer)の
        フィールド名に正規化するだけで、DBには書き込まない(実際の登録はChrome拡張/
        embed版のauto-input-engineがレガシー画面上で行う)。"""
        return {
            "success": True,
            "normalized": _normalize(company_data, self.field_synonyms),
            "entry_entity": self.register_entity,
        }

    @staticmethod
    def _mock_search(keyword: str) -> list[dict]:
        rng = random.Random(_seed_from("company", keyword))
        suffixes = ["株式会社", "商事", "工業", "システムズ"]
        results = []
        for suffix in rng.sample(suffixes, k=min(3, len(suffixes))):
            results.append({
                "name": f"{keyword}{suffix}",
                "name_kana": None,
                "representative": f"{keyword} 代表",
                "address": f"東京都千代田区{keyword}町{rng.randint(1, 9)}-{rng.randint(1, 9)}",
                "tel": f"03-{rng.randint(1000, 9999)}-{rng.randint(1000, 9999)}",
                "website": f"https://www.{keyword.lower()}.example.com",
                "industry": rng.choice(["製造業", "卸売業", "サービス業", "建設業"]),
                "capital": rng.choice([1000000, 5000000, 10000000, 30000000]),
                "employees": rng.randint(5, 500),
            })
        return results


class PropertySearchService:
    # レガシー Property フォーム(demo-legacy-system PROPERTY_FIELDS)の正規フィールド名。
    FIELD_SYNONYMS: dict[str, list[str]] = {
        "Name": ["name", "propertyName", "property_name"],
        "NameKana": ["name_kana", "nameKana"],
        "Address": ["address"],
        "Access": ["access", "traffic"],
        "LandArea": ["land_area", "landArea"],
        "BuildingArea": ["building_area", "buildingArea"],
        "Structure": ["structure"],
        "Floors": ["floors"],
        "BuiltDate": ["built_date", "builtDate"],
        "LandRight": ["land_right", "landRight"],
        "TransactionType": ["transaction_type", "transactionType"],
        "Price": ["price"],
        "MonthlyRent": ["monthly_rent", "monthlyRent"],
        "Facilities": ["facilities"],
    }
    _RESULT_KEYS = (
        "name", "name_kana", "address", "access", "land_area", "building_area",
        "structure", "floors", "built_date", "price", "monthly_rent",
    )
    _PROMPT_TEMPLATE = (
        "あなたはWeb検索ツール(websearch)を使って実在する不動産物件を調査するアシスタントです。\n"
        "必ず websearch ツールで実際に検索を実行してから回答してください(検索せず記憶だけで"
        "答えることは禁止)。\n"
        "検索キーワード: {keyword}\n"
        "検索結果から、キーワードに関連しそうな実在の物件・建物を最大3件ピックアップし、"
        "分かった情報のみをまとめてください。不明な項目は必ず null にし、推測で埋めないこと。\n"
        "出力は説明文・Markdown・コードフェンスを一切含めず、次のJSON形式のみを出力してください:\n"
        '{{"results": [{{"name": "string(必須)", "name_kana": "string|null", '
        '"address": "string|null", "access": "string|null", "land_area": "number|null", '
        '"building_area": "number|null", "structure": "string|null", "floors": "number|null", '
        '"built_date": "string|null", "price": "number|null", "monthly_rent": "number|null"}}]}}'
    )

    def __init__(self, demo_mode: bool = True, ai: AiProvider | None = None):
        self.demo_mode = demo_mode
        self.ai = ai

    async def search(self, keyword: str) -> dict:
        if self.ai is not None and getattr(self.ai, "name", "") == "opencode":
            return await self._ai_search(keyword)
        if self.demo_mode:
            return {"keyword": keyword, "results": self._mock_search(keyword), "source": "mock"}
        raise NotImplementedError("実Web検索API(EXA検索/Google Custom Search等)を接続してください")

    async def _ai_search(self, keyword: str) -> dict:
        ai_text = await self.ai.complete(
            self._PROMPT_TEMPLATE.format(keyword=keyword), tools={"websearch": True}
        )
        if ai_text.startswith("[opencode-error-fallback]"):
            return {"keyword": keyword, "results": [], "source": "opencode-error", "error": ai_text}
        parsed = ai_json_util.extract_json(ai_text)
        raw_results = parsed.get("results")
        results = []
        if isinstance(raw_results, list):
            for item in raw_results:
                if not isinstance(item, dict) or not item.get("name"):
                    continue
                cleaned = {k: item.get(k) for k in self._RESULT_KEYS}
                cleaned["land_area"] = _coerce_number(cleaned["land_area"], float)
                cleaned["building_area"] = _coerce_number(cleaned["building_area"], float)
                cleaned["floors"] = _coerce_number(cleaned["floors"], int)
                cleaned["price"] = _coerce_number(cleaned["price"], int)
                cleaned["monthly_rent"] = _coerce_number(cleaned["monthly_rent"], int)
                results.append(cleaned)
        return {"keyword": keyword, "results": results, "source": "opencode-websearch"}

    def register(self, property_data: dict) -> dict:
        return {"success": True, "normalized": _normalize(property_data, self.FIELD_SYNONYMS)}

    @staticmethod
    def _mock_search(keyword: str) -> list[dict]:
        rng = random.Random(_seed_from("property", keyword))
        structures = ["RC造", "SRC造", "鉄骨造", "木造"]
        results = []
        for i in range(3):
            land = rng.randint(50, 500)
            building = rng.randint(30, land)
            results.append({
                "name": f"{keyword}ビル{i + 1}号",
                "name_kana": None,
                "address": f"東京都港区{keyword}{rng.randint(1, 9)}-{rng.randint(1, 9)}",
                "access": f"最寄駅から徒歩{rng.randint(1, 15)}分",
                "land_area": land,
                "building_area": building,
                "structure": rng.choice(structures),
                "floors": rng.randint(1, 10),
                "built_date": f"20{rng.randint(0, 23):02d}-{rng.randint(1, 12):02d}",
                "price": rng.randint(2000, 50000) * 10000,
                "monthly_rent": rng.randint(10, 300) * 10000,
            })
        return results
