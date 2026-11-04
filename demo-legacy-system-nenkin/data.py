"""
デモ・レガシーシステム（年金照会端末版: 日本年金機構コールセンター/窓口, localhost:5050）
インメモリ「DB」
====================================================================
demo-legacy-system（製造業ERP）/ demo-legacy-system-dealer（自動車ディーラー）/
demo-legacy-system-realestate（不動産仲介）/ demo-legacy-system-koseki（自治体窓口）
と同じ設計方針（7.1章 方式B: 独立インメモリストア + SQLite永続化、main.py側の汎用
レンダリング処理を無改造で再利用）を、年金相談業務（日本年金機構コールセンター/
年金事務所窓口の照会端末）ドメインに置き換えたもの。

「ai-sync-bridgeが刺さるのは COBOL/メインフレームそのものではなく、その手前の
ブラウザ操作の窓口・照会・入力業務」という位置づけの実証として、金融/製造/
不動産/自治体窓口に続く5つ目の業種デモ。コールセンターのオペレーター・年金事務所
窓口の相談員が使う照会端末のフロント（加入記録照会・裁定請求受付・相談受付）を
模したCRUD画面群とし、本体（社会保険オンラインシステム/基礎年金番号管理システム
等の基幹系）には一切触れない前提を踏襲する。

業務ドメイン対応表（他デモとの対比。main.py側の汎用エンジンを流用するための
「型合わせ」）:
  Customer（顧客）        → Insured（被保険者）: 基礎年金番号を持つ本人。年金請求
                            (裁定請求)の請求対象・来所/電話相談の相談対象になる
                            「主役」。
  Property/Product        → ClaimTypes（年金給付種別カタログ）: 老齢基礎年金・
  （商品/物件）              障害基礎年金・遺族厚生年金等、月額見込があり請求明細の
                            対象になる"商品"的ポジション。PensionClaimRequestの
                            明細行対象。
  Order（受注/契約）      → PensionClaimRequest（年金請求/裁定請求受付）: 窓口の
                            主要業務。請求者=Insured、明細行=給付種別×対象月数。
  Supplier（仕入先）      → 使用しない（年金相談業務に「発注先」は存在しないため
                            本デモでは廃止。koseki版と同じ構造上の差分）。
  Employee（従業員）      → Staff（相談員/職員）: コールセンター・年金事務所の
                            相談員/窓口職員。
  Estimate（見積）        → Employer（適用事業所）: 被保険者が加入する事業所照会
                            という、厚生年金業務特有のマスタ照会画面として新設。
  InventoryTransaction     → ContributionHistory（資格異動履歴）: 資格取得/喪失/
  （在庫トランザクション）    種別変更/氏名変更/住所変更/標準報酬月額改定等、
                            被保険者記録上の異動履歴。一覧のみ。
  PurchaseOrder/GoodsReceipt→ 使用しない（発注業務が存在しないドメインのため）。
  ArAp/Profit（財務系集計） → 使用しない（年金相談業務に売掛買掛・利益概念が
                            馴染まないため、本デモでは意図的に採用しない）。
  （新設）VisitReception   → CallReception（来所・電話相談受付）: 相談者の受付・
                            対応状況管理（コールセンター/窓口の双方に対応するため
                            Channel(チャネル)フィールドを追加）。
  （新設）FamilyRegister   → EnrollmentRecord（適用事業所の厚生年金適用記録）:
                            事業所単位の制度適用・加入者数マスタ。
"""
import os
import random
from datetime import datetime, timedelta

import sqlite_store

random.seed(42)

# ---------------------------------------------------------------------------
# 永続化(SQLite)
# ---------------------------------------------------------------------------
_DB_PATH = os.getenv("AISB_NENKIN_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "nenkin.db"))
_conn, _lock = sqlite_store.open_db(_DB_PATH)

# ---------------------------------------------------------------------------
# マスタ用の名称プール
# ---------------------------------------------------------------------------
PERSON_NAMES = [
    ("山田太郎", "ヤマダタロウ", "男"), ("佐藤花子", "サトウハナコ", "女"),
    ("鈴木一郎", "スズキイチロウ", "男"), ("高橋直美", "タカハシナオミ", "女"),
    ("田中健太", "タナカケンタ", "男"), ("伊藤あゆみ", "イトウアユミ", "女"),
    ("渡辺修", "ワタナベオサム", "男"), ("中村ゆり", "ナカムラユリ", "女"),
    ("小林大輔", "コバヤシダイスケ", "男"), ("加藤麻衣", "カトウマイ", "女"),
    ("吉田誠", "ヨシダマコト", "男"), ("山本裕子", "ヤマモトユウコ", "女"),
    ("松本剛", "マツモトツヨシ", "男"), ("井上恵子", "イノウエケイコ", "女"),
    ("木村隆", "キムラタカシ", "男"), ("林由美", "ハヤシユミ", "女"),
    ("斎藤浩二", "サイトウコウジ", "男"), ("清水香織", "シミズカオリ", "女"),
    ("阿部健一", "アベケンイチ", "男"), ("石田美咲", "イシダミサキ", "女"),
    ("橋本亮", "ハシモトリョウ", "男"), ("森田さくら", "モリタサクラ", "女"),
]
DEPARTMENTS = ["お客様相談室", "コールセンター 電話相談係", "年金事務所 給付課", "年金事務所 徴収課"]
POSITIONS = ["室長", "主任相談員", "相談員", "オペレーター", "事務員"]

INSURED_TYPES = ["第1号被保険者", "第2号被保険者", "第3号被保険者"]
INSURED_STATUSES = ["資格あり", "資格喪失", "未加入"]

STREET_NAMES = ["北沢", "梅丘", "代沢", "松原", "羽根木", "桜丘", "経堂", "祖師谷", "成城", "喜多見"]
CITY_NAME = "東京都世田谷区"

INDUSTRIES = ["製造業", "卸売・小売業", "建設業", "情報通信業", "医療・福祉", "運輸業", "飲食サービス業"]

CLAIM_TYPES = [
    {"Id": "PT01", "Name": "老齢基礎年金", "UnitPrice": 65000},
    {"Id": "PT02", "Name": "老齢厚生年金", "UnitPrice": 90000},
    {"Id": "PT03", "Name": "障害基礎年金(1級)", "UnitPrice": 81000},
    {"Id": "PT04", "Name": "障害基礎年金(2級)", "UnitPrice": 65000},
    {"Id": "PT05", "Name": "遺族基礎年金", "UnitPrice": 65000},
    {"Id": "PT06", "Name": "遺族厚生年金", "UnitPrice": 50000},
    {"Id": "PT07", "Name": "加給年金額", "UnitPrice": 20000},
    {"Id": "PT08", "Name": "未支給年金", "UnitPrice": 65000},
]

CLAIM_REQUEST_STATUSES = ["受付", "審査中", "裁定済", "却下", "差戻し"]
CLAIM_PURPOSES = ["老齢給付裁定請求", "障害給付裁定請求", "遺族給付裁定請求", "額改定請求", "年金分割請求", "受給者現況届"]
RECEPTION_CHANNELS = ["窓口", "電話(コールセンター)"]
RECEPTION_PURPOSES = ["年金見込額試算", "裁定請求手続き", "加入記録照会", "各種届出", "未納保険料相談", "年金分割相談", "現況確認", "その他"]
RECEPTION_STATUSES = ["待機中", "対応中", "保留", "完了", "再連絡"]
CONTRIBUTION_CHANGE_TYPES = ["資格取得", "資格喪失", "種別変更", "氏名変更", "住所変更", "標準報酬月額改定", "産前産後免除適用"]
PENSION_TYPES = ["厚生年金保険", "厚生年金基金", "共済組合"]


def _rand_date(min_days=-180, max_days=30):
    """base(今日)から見て [min_days, max_days] 日オフセットの日付を返す（負=過去/正=未来）。"""
    base = datetime(2026, 7, 25)
    delta = random.randint(min_days, max_days)
    return (base + timedelta(days=delta)).strftime("%Y-%m-%d")


def _birth_date(min_age=20, max_age=90):
    base = datetime(2026, 7, 25)
    age_days = random.randint(min_age * 365, max_age * 365)
    return (base - timedelta(days=age_days)).strftime("%Y-%m-%d")


def _address():
    return f"{CITY_NAME}{random.choice(STREET_NAMES)}{random.randint(1,5)}-{random.randint(1,20)}-{random.randint(1,10)}"


def _tel():
    return f"0{random.randint(1,9)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"


def _basic_pension_number_masked():
    return f"****-****-{random.randint(1000,9999)}"


# ---------------------------------------------------------------------------
# Employers（適用事業所） — 先に事業所を作り、被保険者を事業所に所属させる
# ---------------------------------------------------------------------------
employers = sqlite_store.PersistentDict(_conn, _lock, "employers")
if not employers:
    for i in range(1, 15):
        eid = f"J{i:04d}"
        employers[eid] = {
            "Id": eid,
            "Name": f"株式会社{random.choice(STREET_NAMES)}{'商事' if i % 2 == 0 else '工業'}",
            "Address": _address(),
            "Industry": random.choice(INDUSTRIES),
            "MemberCount": 0,
            "CreatedAt": _rand_date(-1800, -30),
        }
employer_ids = list(employers.keys())

# ---------------------------------------------------------------------------
# Insureds（被保険者） — 事業所に所属させる(第1号は事業所なし=国民年金)
# ---------------------------------------------------------------------------
insureds = sqlite_store.PersistentDict(_conn, _lock, "insureds")
if not insureds:
    idx = 1
    for eid in employer_ids:
        emp = employers[eid]
        member_count = random.randint(1, 4)
        for m in range(member_count):
            iid = f"P{idx:05d}"
            name, kana, gender = PERSON_NAMES[(idx - 1) % len(PERSON_NAMES)]
            insureds[iid] = {
                "Id": iid,
                "Name": name,
                "NameKana": kana,
                "Gender": gender,
                "BirthDate": _birth_date(20, 90),
                "InsuredType": "第2号被保険者",
                "EmployerId": eid,
                "Address": _address(),
                "Tel": _tel(),
                "BasicPensionNumber": _basic_pension_number_masked(),
                "Status": random.choices(INSURED_STATUSES, weights=[88, 8, 4])[0],
                "AcquisitionDate": _rand_date(-5000, -30),
                "Notes": "",
                "CreatedAt": _rand_date(-5000, -30),
            }
            idx += 1
        emp["MemberCount"] = member_count
        employers[eid] = emp  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
    # 第1号/第3号被保険者(事業所に属さない自営業/被扶養配偶者)も少数追加
    for _ in range(12):
        iid = f"P{idx:05d}"
        name, kana, gender = PERSON_NAMES[(idx - 1) % len(PERSON_NAMES)]
        insureds[iid] = {
            "Id": iid,
            "Name": name,
            "NameKana": kana,
            "Gender": gender,
            "BirthDate": _birth_date(20, 90),
            "InsuredType": random.choice(["第1号被保険者", "第3号被保険者"]),
            "EmployerId": "",
            "Address": _address(),
            "Tel": _tel(),
            "BasicPensionNumber": _basic_pension_number_masked(),
            "Status": random.choices(INSURED_STATUSES, weights=[88, 8, 4])[0],
            "AcquisitionDate": _rand_date(-5000, -30),
            "Notes": "",
            "CreatedAt": _rand_date(-5000, -30),
        }
        idx += 1
insured_ids = list(insureds.keys())


def claim_catalog():
    """PensionClaimRequest の明細行ピッカー用アダプタ(Id/Name/UnitPriceの形は元々一致)。"""
    return {c["Id"]: c for c in CLAIM_TYPES}


def insured_options():
    return [(p["Id"], f'{p["Name"]}（{p["Id"]}）') for p in insureds.values()]


# ---------------------------------------------------------------------------
# EnrollmentRecords（適用事業所の厚生年金適用記録） — 事業所ごとに1件の適用記録
# ---------------------------------------------------------------------------
enrollment_records = sqlite_store.PersistentDict(_conn, _lock, "enrollment_records")
if not enrollment_records:
    for i, eid in enumerate(employer_ids, start=1):
        emp = employers[eid]
        rid = f"N{i:04d}"
        enrollment_records[rid] = {
            "Id": rid,
            "EmployerName": emp["Name"],
            "PensionOffice": f"{random.choice(STREET_NAMES)}年金事務所",
            "PensionType": random.choices(PENSION_TYPES, weights=[85, 5, 10])[0],
            "InsuredCount": emp["MemberCount"],
            "ApplicationDate": _rand_date(-3650, -180),
            "Notes": "",
            "CreatedAt": _rand_date(-3650, -180),
        }
enrollment_record_ids = list(enrollment_records.keys())

# ---------------------------------------------------------------------------
# Staff（相談員/窓口職員）
# ---------------------------------------------------------------------------
staff = sqlite_store.PersistentDict(_conn, _lock, "staff")
if not staff:
    for i in range(1, 13):
        sid = f"S{i:03d}"
        name, _, _ = PERSON_NAMES[(i - 1) % len(PERSON_NAMES)]
        staff[sid] = {
            "Id": sid,
            "Name": name,
            "Department": random.choice(DEPARTMENTS),
            "Position": random.choice(POSITIONS),
            "CounterNo": f"{random.randint(1,8)}番窓口" if random.random() > 0.4 else f"内線{random.randint(1000,1999)}",
            "Email": f"staff{i:03d}@nenkin-legacy.example.jp",
            "Tel": _tel(),
            "HireDate": _rand_date(-5000, -100),
            "CreatedAt": _rand_date(-5000, -100),
        }
staff_ids = list(staff.keys())

# ---------------------------------------------------------------------------
# PensionClaimRequests（年金請求/裁定請求受付） + PensionClaimRequestItems（明細行）
# 元ERPのOrderに相当。請求者=Insured、明細行=給付種別×対象月数(支給見込額概算)。
# ---------------------------------------------------------------------------
pension_claim_requests = sqlite_store.PersistentDict(_conn, _lock, "pension_claim_requests")
pension_claim_request_items = sqlite_store.PersistentDict(_conn, _lock, "pension_claim_request_items")
if not pension_claim_requests:
    for i in range(1, 34):
        cid = f"CL{1000 + i}"
        applicant = insureds[random.choice(insured_ids)]
        items = []
        for _ in range(random.randint(1, 2)):
            ct = random.choice(CLAIM_TYPES)
            qty = random.randint(1, 12)
            items.append({"ProductId": ct["Id"], "ProductName": ct["Name"], "Quantity": qty,
                          "UnitPrice": ct["UnitPrice"], "Amount": qty * ct["UnitPrice"]})
        total = sum(it["Amount"] for it in items)
        req_date = _rand_date(-120, 0)
        pension_claim_requests[cid] = {
            "Id": cid,
            "CustomerId": applicant["Id"],
            "CustomerName": applicant["Name"],
            "OrderDate": req_date,
            "DeliveryDate": _rand_date(-90, 30),  # 裁定結果通知予定日
            "TotalAmount": total,
            "Status": random.choice(CLAIM_REQUEST_STATUSES),
            "Purpose": random.choice(CLAIM_PURPOSES),
            "Notes": "",
            "CreatedAt": req_date,
        }
        pension_claim_request_items[cid] = items
pension_claim_request_ids = list(pension_claim_requests.keys())

# ---------------------------------------------------------------------------
# CallReceptions（来所・電話相談受付） — ワークフロー色の強い新設エンティティ
# ---------------------------------------------------------------------------
call_receptions = sqlite_store.PersistentDict(_conn, _lock, "call_receptions")
if not call_receptions:
    for i in range(1, 41):
        vid = f"CR{1000 + i}"
        visitor = insureds[random.choice(insured_ids)]
        counselor = staff[random.choice(staff_ids)] if random.random() > 0.15 else None
        call_receptions[vid] = {
            "Id": vid,
            "VisitorName": visitor["Name"],
            "VisitorId": visitor["Id"],
            "Channel": random.choice(RECEPTION_CHANNELS),
            "Purpose": random.choice(RECEPTION_PURPOSES),
            "ReceptionTime": _rand_date(-14, 0),
            "CounterNo": counselor["CounterNo"] if counselor else "",
            "EmployeeId": counselor["Id"] if counselor else "",
            "EmployeeName": counselor["Name"] if counselor else "未割当",
            "Status": random.choice(RECEPTION_STATUSES),
            "Notes": "",
            "CreatedAt": _rand_date(-14, 0),
        }
call_reception_ids = list(call_receptions.keys())

# ---------------------------------------------------------------------------
# ContributionHistory（資格異動履歴） — 元ERPのInventoryTransactionに相当。一覧のみ。
# ---------------------------------------------------------------------------
contribution_history = sqlite_store.PersistentList(_conn, _lock, "contribution_history")
if not contribution_history:
    for i in range(1, 61):
        iid = random.choice(insured_ids)
        p = insureds[iid]
        contribution_history.append({
            "Id": f"CH{i:05d}",
            "ProductId": iid,
            "ProductName": p["Name"],
            "Type": random.choice(CONTRIBUTION_CHANGE_TYPES),
            "Date": _rand_date(-720, 0),
            "Notes": "",
        })
# main.py 側は元ERPと同じ変数名(inventory_transactions)で参照するためのエイリアス。
inventory_transactions = contribution_history


# ---------------------------------------------------------------------------
# ID採番（新規登録用）
# ---------------------------------------------------------------------------
_counters = {
    "Insured": len(insureds), "Employer": len(employers), "EnrollmentRecord": len(enrollment_records),
    "Staff": len(staff), "PensionClaimRequest": len(pension_claim_requests),
    "CallReception": len(call_receptions),
}
_ID_FORMATS = {
    "Insured": "P{:05d}", "Employer": "J{:04d}", "EnrollmentRecord": "N{:04d}",
    "Staff": "S{:03d}", "PensionClaimRequest": "CL{:04d}", "CallReception": "CR{:04d}",
}


def next_id(entity: str) -> str:
    _counters[entity] += 1
    n = _counters[entity]
    fmt = _ID_FORMATS[entity]
    # CL/CRは元データが1000番台始まりなので揃える
    if entity in ("PensionClaimRequest", "CallReception"):
        return fmt.format(1000 + n)
    return fmt.format(n)
