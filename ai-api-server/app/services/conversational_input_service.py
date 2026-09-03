"""
Conversational Input Service (Scoped)
実装ロードマップ Task#6: README 5.4.7「自然言語→フォームデータ変換
(ConversationalInputService相当)」= POST /api/conversational-input
（panel-conv-input.js: 自然文入力→フォームマッピング＋不足フィールド表示）。

nlsql_service.py と同じ「AIには構造化JSONだけを生成させ、実行/反映は
このモジュールがホワイトリスト検証したものに限る」方針を踏襲する
(fieldはSCREEN_FIELDSに定義した表記以外を一切採用しない)。

6.1節の設計原則(レガシー側はAI-Sync Bridgeの存在を知らない)により、実際のDOM入力は
Chrome拡張のauto-input-engineが行う。このサービスの責務は
「自然文→フィールド値の解決」までで、workflow_step_runner._run_auto_input と
同じく実DOM書き込みは行わない。
"""
import uuid

from app.config import Settings
from app.services import ai_json_util
from app.services.ai_client import AiProvider
from app.services.demo_data import DemoDataStore
from app.services.normalize_util import normalize as _normalize

# 5.4.7: 画面種別別フィールド定義(5画面)。値は README記載の全フィールドをそのまま採用。
SCREEN_FIELDS: dict[str, list[str]] = {
    "order-input": ["顧客名", "顧客コード", "商品名", "商品コード", "数量", "単価", "金額", "日付", "納期", "備考"],
    "customer-register": ["会社名", "カナ", "TEL", "郵便番号", "住所", "与信限度額", "備考"],
    "estimate-mgmt": ["顧客名", "顧客コード", "日付", "有効期限", "商品名", "数量", "単価", "金額"],
    "invoice-mgmt": ["顧客名", "日付", "支払期日", "金額", "関連受注"],
    "supplier-mgmt": ["仕入先名", "TEL", "住所", "担当者", "与信枠"],
}

# 2026-09-01: register() — 仕入先検索(web_search_service.py)/OCR(ocr_service.py)と同じ
# 「登録用データを作る→新規登録ページを開いて自動入力」導線を自然言語入力にも展開する。
# SCREEN_FIELDSの日本語ラベルを、各画面が実際に遷移するレガシー新規登録フォームの
# name属性に正規化するだけの純粋関数(DBアクセスなし)。
#
# order-input/estimate-mgmt は entry_items.html(明細行つき動的フォーム)を使うため、
# ヘッダー項目(顧客/日付/備考等)のみ対応可能。商品名/数量/単価等の明細行は
# auto-input-engine.js が「name属性の完全一致のみ」で書き込む方針(曖昧一致・行追加の
# 自動操作はしない)のため対象外とし、フォーム上に対応する input が存在しない結果
# fillForm() 側で自然にスキップされる(=未対応フィールドとして明示される)。
# これはOCR側がOrder/Estimate/Invoice等をFK select理由で対象外にしたのとは異なる判断
# 基準(会話入力はエンティティ解決で顧客コードを補完できるため対象に含められる)だが、
# 「書き込めるものだけ書き込み、書き込めないものは黙って落とさずスキップとして見せる」
# という透明性の方針自体は auto-input-engine.js 全体で共通。
SCREEN_ENTRY_ENTITY: dict[str, str] = {
    "order-input": "Order",
    "customer-register": "Customer",
    "estimate-mgmt": "Estimate",
    "invoice-mgmt": "Invoice",
    "supplier-mgmt": "Supplier",
}

# legacyフォームのname属性 -> 対応するSCREEN_FIELDSの日本語ラベル(表記揺れは無いため
# 1候補のみ)。erp/dealerでOrder/Estimate/Customer/Supplier/Invoiceのフィールド名は
# 完全に共通(demo-legacy-system(-dealer)双方のmain.pyで確認済み)なので、OCR側の
# FIELD_SYNONYMS_BY_INSTANCEと違いinstance分岐は不要。
SCREEN_FIELD_SYNONYMS: dict[str, dict[str, list[str]]] = {
    "order-input": {  # entry_items.html: ヘッダー項目のみ(明細行は対象外、上のコメント参照)
        "customerId": ["顧客コード"],
        "orderDate": ["日付"],
        "deliveryDate": ["納期"],
        "notes": ["備考"],
    },
    "customer-register": {
        "Name": ["会社名"],
        "NameKana": ["カナ"],
        "Tel": ["TEL"],
        "PostalCode": ["郵便番号"],
        "Address": ["住所"],
        "CreditLimit": ["与信限度額"],
        "Notes": ["備考"],
    },
    "estimate-mgmt": {  # entry_items.html: ヘッダー項目のみ
        "customerId": ["顧客コード"],
        "estimateDate": ["日付"],
        "validUntil": ["有効期限"],
    },
    "invoice-mgmt": {
        "CustomerId": ["顧客コード"],
        "InvoiceDate": ["日付"],
        "DueDate": ["支払期日"],
        "TotalAmount": ["金額"],
        "OrderId": ["関連受注"],
    },
    "supplier-mgmt": {
        "Name": ["仕入先名"],
        "Tel": ["TEL"],
        "Address": ["住所"],
        "ContactPerson": ["担当者"],
        "CreditAmount": ["与信枠"],
    },
}

# README本文には必須/任意の区別が明記されていないため、業務上レコード作成に最低限
# 要る項目を実装判断として定義する(不足フィールド検出=missingFieldsの算出に使う)。
_REQUIRED_FIELDS: dict[str, list[str]] = {
    "order-input": ["顧客名", "商品名", "数量"],
    "customer-register": ["会社名", "TEL", "住所"],
    "estimate-mgmt": ["顧客名", "商品名", "数量", "単価"],
    "invoice-mgmt": ["顧客名", "金額", "支払期日"],
    "supplier-mgmt": ["仕入先名", "TEL"],
}


class ConversationalInputService:
    def __init__(self, settings: Settings, ai: AiProvider, store: DemoDataStore):
        self.settings = settings
        self.ai = ai
        self.store = store

    @staticmethod
    def _history_key(conversation_id: str) -> str:
        return f"convinput:{conversation_id}"

    def register(self, fields: dict, target_screen: str) -> dict:
        """parse()が返したinput_mappingsをフロント側で {field: value} に組み直したものを、
        target_screenのレガシー新規登録フォームのname属性に正規化する。ocr_service.py の
        register()と同じ位置付けでDBアクセスは一切行わない。"""
        if target_screen not in SCREEN_ENTRY_ENTITY:
            raise ValueError(
                f"未対応のtargetScreen: {target_screen}({'/'.join(SCREEN_ENTRY_ENTITY)}のいずれか)"
            )
        return {
            "success": True,
            "normalized": _normalize(fields, SCREEN_FIELD_SYNONYMS[target_screen]),
            "entry_entity": SCREEN_ENTRY_ENTITY[target_screen],
        }

    @staticmethod
    def _build_prompt(target_screen: str, fields: list[str], message: str) -> str:
        return (
            f"あなたはフォーム入力アシスタントです。対象画面は「{target_screen}」で、"
            f"利用可能なフィールド: {', '.join(fields)}\n\n"
            f"ユーザーの入力:「{message}」\n\n"
            "この入力から読み取れるフィールド値を、以下のJSON形式のみで出力してください"
            "(説明文・コードブロック記法は一切不要。JSON以外の文字は出力しないこと):\n"
            '{"intent": "create|update|query", "fields": {"フィールド名": "値", ...}}\n'
            "フィールド名は上記リストの表記のまま使うこと。読み取れないフィールドは含めないこと。"
        )

    def _resolve_entities(self, fields: dict, resolved_from_ai: set[str]) -> dict:
        """顧客名/商品名からDB検索で正式コードを解決する(5.4.7の「エンティティ解決」)。
        AIが直接出力した値ではなく本サービスが補完した値なので、呼び出し側の
        input_mappings では confidence を medium にする(resolved_from_aiに含めない)。"""
        customer_name = fields.get("顧客名")
        if customer_name and "顧客コード" not in fields:
            for c in self.store.list_customers():
                if customer_name in str(c.get("name", "")) or str(c.get("name", "")) in customer_name:
                    fields["顧客コード"] = str(c["id"])
                    break

        product_name = fields.get("商品名")
        if product_name:
            for p in self.store.list_products():
                if product_name in str(p.get("name", "")) or str(p.get("name", "")) in product_name:
                    if "商品コード" not in fields:
                        fields["商品コード"] = p.get("sku", "")
                    if "単価" not in fields and p.get("unit_cost") is not None:
                        fields["単価"] = str(p["unit_cost"])
                    break
        return fields

    async def parse(
        self,
        message: str,
        target_screen: str,
        screen_context: dict | None = None,
        conversation_id: str | None = None,
    ) -> dict:
        if target_screen not in SCREEN_FIELDS:
            raise ValueError(f"未対応のtargetScreen: {target_screen}({'/'.join(SCREEN_FIELDS)}のいずれか)")
        if not self.settings.demo_mode:
            raise NotImplementedError("本番DBリポジトリ未接続: profiles/<your-system> で実装してください")

        conversation_id = conversation_id or uuid.uuid4().hex
        allowed_fields = SCREEN_FIELDS[target_screen]

        prompt = self._build_prompt(target_screen, allowed_fields, message)
        ai_text = await self.ai.complete(prompt)
        raw = ai_json_util.extract_json(ai_text)

        raw_fields = raw.get("fields") if isinstance(raw.get("fields"), dict) else {}
        # ホワイトリスト検証: SCREEN_FIELDSに定義された表記以外は採用しない(nlsql_serviceと同方針)
        fields = {k: v for k, v in raw_fields.items() if k in allowed_fields and v not in (None, "")}
        resolved_from_ai = set(fields.keys())

        self._resolve_entities(fields, resolved_from_ai)

        intent = raw.get("intent") if raw.get("intent") in ("create", "update", "query") else "create"

        required = _REQUIRED_FIELDS.get(target_screen, [])
        missing_fields = [f for f in required if not fields.get(f)]
        confidence = round((len(required) - len(missing_fields)) / len(required), 2) if required else (1.0 if fields else 0.0)

        input_mappings = [
            {"field": name, "value": value, "confidence": "high" if name in resolved_from_ai else "medium"}
            for name, value in fields.items()
        ]

        if not raw_fields:
            response = "入力内容からフィールドを読み取れませんでした。もう少し具体的に入力してください。"
        elif missing_fields:
            response = f"{len(fields)}件のフィールドを認識しました。不足項目: {', '.join(missing_fields)}"
        else:
            response = f"{len(fields)}件のフィールドを認識しました。自動入力の準備ができています。"

        key = self._history_key(conversation_id)
        self.store.append_history(key, "user", message)
        self.store.append_history(key, "assistant", response)

        return {
            "response": response,
            "conversation_id": conversation_id,
            "input_mappings": input_mappings,
            "intent": intent,
            "missing_fields": missing_fields,
            "confidence": confidence,
        }
