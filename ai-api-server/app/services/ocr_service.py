"""
OCR Service (Scoped)
2026-08-21改訂: web_search_service.py と同じ考え方で実AI接続に切り替えた。
「実OCRエンジン(pytesseract等)への接続が必要な未実装の拡張点」という前提だったが、
opencode serve の GET /config/providers を実地確認したところ、既定モデル
(deepseek-v4-flash-free等)は capabilities.input.image=false でvision非対応な一方、
mimo-v2.5-free が image=true(vision対応)であることを確認済み。よってpytesseract等を
別途導入しなくても、opencodeプロバイダ経由でvisionモデルに画像を渡せば実OCRが可能。

2026-08-21追記: vision対応モデルは capabilities.input.pdf が全モデルfalseでPDF直接入力
不可のままだが、「PDFを画像化してから渡す」変換自体は接続不要でこちら側だけで完結する。
pypdfium2(pure wheel, poppler等システム依存なし)でページ毎にPNGへラスタライズし、既存の
_ai_extract() を1ページ=1回のvision呼び出しとして使い回す設計にした。

優先順位:
  1. 画像ファイル(image/*)かつ ai プロバイダがvision対応 -> _ai_extract() で1回読ませる。
  2. PDFかつ ai プロバイダがvision対応 -> _pdf_to_page_images() でページ毎にPNG化し、
     ページ単位で _ai_extract() → 結果をマージ(_merge_page_results())。
     画像化に失敗した場合(壊れたPDF等)は3.相当のフォールバックに落とす。
  3. 上記以外で demo_mode=true -> 従来通りファイル名/サイズからの決定的な擬似結果。
  4. それ以外(prod かつ 非対応) -> NotImplementedError の拡張点として残す。

2026-08-31追記: register() を追加。仕入先検索(web_search_service.py)の「登録用データを
作る→新規登録ページを開いて自動入力」と同じ導線を、OCR結果からも辿れるようにした。
extract()が返すfields(帳票の項目名→値)を、選択されたエンティティのレガシーフォームの
name属性に正規化するだけの純粋関数で、DBアクセスは無い。詳細はOcrServiceクラスの
コメント参照。
"""
import io
import re

from app.services import ai_json_util
from app.services.ai_client import AiProvider
from app.services.normalize_util import normalize as _normalize

MAX_PDF_PAGES = 5  # 1リクエストでvisionをN回叩くコスト/レイテンシの上限

_PROMPT = (
    "あなたは請求書・領収書などの帳票画像を読み取るOCRアシスタントです。\n"
    "添付された画像に実際に写っている文字だけを読み取ってください。写っていない項目は"
    "推測で埋めず必ず null にしてください。\n"
    "出力は説明文・Markdown・コードフェンスを一切含めず、次のJSON形式のみを出力してください:\n"
    '{"extracted_text": "画像内の文字を読み取った順にまとめたテキスト", '
    '"fields": {"項目名": "値", ...}, "confidence": 0.0〜1.0の数値(読み取りやすさの自己評価)}'
)


class OcrService:
    # 2026-08-31: register() — OCR結果(fields)をレガシー新規登録フォームのフィールド名
    # (name属性)に正規化する。web_search_service.py の CompanySearchService.register() と
    # 同じ考え方(normalize_util.normalize())で、DBアクセスは一切行わない。
    #
    # 対象エンティティは「他エンティティをDBレコード参照のselectで持たない自由入力
    # フォーム」に限定する(Order/Estimate/PurchaseOrder/Invoice/GoodsReceipt/
    # ServiceOrderはCustomerId/SupplierId/ProductId等のFK selectが必須で、OCRはそもそも
    # 既存レコードのIDを読み取れないため対象外——CompanySearchService/PropertySearchService
    # がCustomer/Supplier/Propertyのみを登録先にしているのと同じ判断基準)。
    #   - erp: Customer, Supplier, Employee, Property
    #   - dealer: Customer, Supplier, Employee (Propertyエンティティ自体が存在しない)
    #
    # キーはレガシーフォームの name 属性、値は demo-legacy-system(-dealer) の
    # CUSTOMER_FIELDS 等に表示される日本語ラベルそのもの(OCRサンプル画像もこの
    # ラベル文字列で生成しているため、実読み取り結果のキーとそのまま一致する)。
    FIELD_SYNONYMS_BY_INSTANCE: dict[str, dict[str, dict[str, list[str]]]] = {
        "erp": {
            "Customer": {
                "Name": ["会社名", "名前", "氏名", "取引先", "name", "company_name"],
                "NameKana": ["カナ", "フリガナ", "name_kana"],
                "Representative": ["代表者", "代表者名", "representative"],
                "PostalCode": ["郵便番号", "〒", "postal_code"],
                "Address": ["住所", "所在地", "address"],
                "Tel": ["TEL", "電話", "電話番号", "tel"],
                "Fax": ["FAX", "fax"],
                "Website": ["Webサイト", "website", "url"],
                "Capital": ["資本金", "capital"],
                "Employees": ["従業員数", "employees"],
                "Industry": ["業種", "industry"],
                "CreditLimit": ["与信限度額", "credit_limit"],
                "Notes": ["備考", "notes", "memo"],
            },
            "Supplier": {
                "Name": ["仕入先名", "会社名", "取引先", "name"],
                "Category": ["カテゴリ", "業種", "category"],
                "Tel": ["TEL", "電話", "電話番号", "tel"],
                "Address": ["住所", "所在地", "address"],
                "ContactPerson": ["担当者", "担当者名", "contact_person"],
                "CreditAmount": ["与信枠", "credit_amount"],
                "PaymentTerms": ["支払条件", "payment_terms"],
                "Notes": ["備考", "notes", "memo"],
            },
            "Employee": {
                "Name": ["氏名", "名前", "name"],
                "Department": ["部署", "department"],
                "Position": ["役職", "position"],
                "Email": ["メール", "メールアドレス", "email"],
                "Tel": ["TEL", "電話", "電話番号", "tel"],
                "HireDate": ["入社日", "hire_date"],
            },
            "Property": {
                "Name": ["物件名", "name"],
                "NameKana": ["フリガナ", "カナ", "name_kana"],
                "Address": ["住所", "所在地", "address"],
                "Access": ["交通", "access"],
                "LandArea": ["敷地面積", "land_area"],
                "BuildingArea": ["建物面積", "building_area"],
                "Structure": ["構造", "structure"],
                "Floors": ["階数", "floors"],
                "BuiltDate": ["築年月", "built_date"],
                "LandRight": ["権利形態", "land_right"],
                "TransactionType": ["取引形態", "transaction_type"],
                "Price": ["価格", "金額", "price"],
                "MonthlyRent": ["月額賃料", "monthly_rent"],
                "Facilities": ["設備", "facilities"],
            },
        },
        "dealer": {
            "Customer": {
                "Name": ["氏名", "会社名", "名前", "取引先", "name"],
                "NameKana": ["カナ", "フリガナ", "name_kana"],
                "CustomerType": ["顧客区分", "customer_type"],
                "PostalCode": ["郵便番号", "〒", "postal_code"],
                "Address": ["住所", "所在地", "address"],
                "Tel": ["TEL", "電話", "電話番号", "tel"],
                "Email": ["メール", "メールアドレス", "email"],
                "DriverLicenseNo": ["運転免許証番号", "免許証番号", "driver_license_no"],
                "CreditLimit": ["与信限度額", "ローン限度額", "credit_limit"],
                "Notes": ["備考", "notes", "memo"],
            },
            "Supplier": {
                "Name": ["仕入先名", "会社名", "取引先", "name"],
                "Category": ["カテゴリ", "仕入区分", "category"],
                "Tel": ["TEL", "電話", "電話番号", "tel"],
                "Address": ["住所", "所在地", "address"],
                "ContactPerson": ["担当者", "担当者名", "contact_person"],
                "CreditAmount": ["与信枠", "credit_amount"],
                "PaymentTerms": ["支払条件", "payment_terms"],
                "Notes": ["備考", "notes", "memo"],
            },
            "Employee": {
                "Name": ["氏名", "名前", "name"],
                "Department": ["部署", "department"],
                "Position": ["役職", "position"],
                "Email": ["メール", "メールアドレス", "email"],
                "Tel": ["TEL", "電話", "電話番号", "tel"],
                "HireDate": ["入社日", "hire_date"],
            },
        },
    }

    def __init__(self, demo_mode: bool = True, ai: AiProvider | None = None, instance: str = "erp"):
        self.demo_mode = demo_mode
        self.ai = ai
        self.instance = instance if instance in self.FIELD_SYNONYMS_BY_INSTANCE else "erp"

    def entities(self) -> list[str]:
        """この業態(instance)でOCR結果のジャンプ/自動入力先として選べるエンティティ名一覧。"""
        return list(self.FIELD_SYNONYMS_BY_INSTANCE[self.instance].keys())

    def register(self, fields: dict, entity: str) -> dict:
        """OCRのfields(帳票から読み取った項目名→値)を、指定エンティティのレガシー新規
        登録フォームのフィールド名に正規化する。DBには書き込まない(実際の書き込みは
        フロント側のauto-input-engine.openAndFill()がユーザーの明示操作で行う)。"""
        entity_synonyms = self.FIELD_SYNONYMS_BY_INSTANCE[self.instance]
        if entity not in entity_synonyms:
            raise ValueError(
                f"entity '{entity}' はこの業態(instance={self.instance})のOCR登録先として対応していません"
                f"(対応エンティティ: {', '.join(entity_synonyms.keys())})"
            )
        return {
            "success": True,
            "normalized": _normalize(fields, entity_synonyms[entity]),
            "entry_entity": entity,
        }

    async def extract(self, filename: str, content: bytes, mime: str | None = None) -> dict:
        is_image = bool(mime) and mime.startswith("image/")
        is_pdf = (mime == "application/pdf") or filename.lower().endswith(".pdf")
        vision_ready = self.ai is not None and getattr(self.ai, "supports_vision", False)

        if vision_ready and is_image:
            return await self._ai_extract(filename, content, mime)

        if vision_ready and is_pdf:
            page_images = self._pdf_to_page_images(content)
            if page_images is not None:
                if not page_images:
                    return {
                        "filename": filename,
                        "extracted_text": "",
                        "fields": {},
                        "confidence": 0.0,
                        "source": "opencode-vision-pdf",
                    }
                page_results = [
                    await self._ai_extract(filename, png_bytes, "image/png")
                    for png_bytes in page_images
                ]
                return self._merge_page_results(filename, page_results)
            # 画像化に失敗(壊れたPDF等) -> 下のモック/例外フォールバックへ

        if self.demo_mode:
            result = self._mock_extract(filename, content)
            result["source"] = "mock"
            return result
        raise NotImplementedError(
            "実OCRエンジンに接続してください(現状 opencode + vision対応モデルのみ画像/PDFを実処理できます。"
            "非vision構成は未対応の拡張点です)"
        )

    def _pdf_to_page_images(self, content: bytes) -> list[bytes] | None:
        """PDFの各ページをPNGバイト列にラスタライズする。pypdfium2未導入・破損PDF等で
        変換自体ができない場合は None を返し、呼び出し側でフォールバックさせる。"""
        try:
            import pypdfium2 as pdfium
        except ImportError:
            return None
        try:
            pdf = pdfium.PdfDocument(content)
        except Exception:
            return None
        images: list[bytes] = []
        try:
            for i in range(min(len(pdf), MAX_PDF_PAGES)):
                page = pdf[i]
                bitmap = page.render(scale=2.0)  # 低解像度だと細かい文字が潰れるため2x
                pil_image = bitmap.to_pil()
                buf = io.BytesIO()
                pil_image.save(buf, format="PNG")
                images.append(buf.getvalue())
        finally:
            pdf.close()
        return images

    def _merge_page_results(self, filename: str, page_results: list[dict]) -> dict:
        """ページ毎のvision結果を1つのOCR結果にマージする。fieldsは先勝ち(空文字は
        後続ページの値で埋める)、extracted_textはページ区切り付きで連結、confidenceは平均。"""
        texts = []
        fields: dict[str, str] = {}
        confidences = []
        for i, r in enumerate(page_results, start=1):
            page_text = r.get("extracted_text") or ""
            if page_text:
                texts.append(f"--- ページ{i} ---\n{page_text}")
            for k, v in (r.get("fields") or {}).items():
                if not fields.get(k) and v:
                    fields[k] = v
            confidences.append(r.get("confidence") or 0.0)
        return {
            "filename": filename,
            "extracted_text": "\n".join(texts),
            "fields": fields,
            "confidence": (sum(confidences) / len(confidences)) if confidences else 0.0,
            "source": "opencode-vision-pdf",
        }

    async def _ai_extract(self, filename: str, content: bytes, mime: str) -> dict:
        ai_text = await self.ai.complete_vision(_PROMPT, content, mime)
        parsed = ai_json_util.extract_json(ai_text)
        extracted_text = parsed.get("extracted_text") or ""
        fields = parsed.get("fields")
        if not isinstance(fields, dict):
            fields = {}
        fields = {str(k): str(v) for k, v in fields.items() if v is not None}
        confidence = parsed.get("confidence")
        try:
            confidence = float(confidence)
        except (TypeError, ValueError):
            confidence = 0.0
        confidence = max(0.0, min(1.0, confidence))
        return {
            "filename": filename,
            "extracted_text": extracted_text,
            "fields": fields,
            "confidence": confidence,
            "source": "opencode-vision",
        }

    def _mock_extract(self, filename: str, content: bytes) -> dict:
        size_kb = max(1, len(content) // 1024)
        text = (
            f"請求書番号: INV-{size_kb:04d}\n"
            f"発行日: 2026-07-23\n"
            f"金額: ¥{size_kb * 1234}\n"
            f"取引先: サンプル株式会社"
        )
        fields = {}
        for line in text.splitlines():
            if ":" in line or "：" in line:
                key, val = re.split("[:：]", line, maxsplit=1)
                fields[key.strip()] = val.strip()
        return {
            "filename": filename,
            "extracted_text": text,
            "fields": fields,
            "confidence": 0.87,
        }
