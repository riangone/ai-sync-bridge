"""
デモ・レガシーシステム（自治体窓口版: 戸籍・住基, localhost:5040） インメモリ「DB」
====================================================================
demo-legacy-system（製造業ERP）/ demo-legacy-system-dealer（自動車ディーラー）/
demo-legacy-system-realestate（不動産仲介）と同じ設計方針（7.1章 方式B: 独立
インメモリストア + SQLite永続化、main.py側の汎用レンダリング処理を無改造で
再利用）を、自治体窓口業務（戸籍・住民基本台帳）ドメインに置き換えたもの。

「ai-sync-bridgeが刺さるのは COBOL/メインフレームそのものではなく、その手前の
ブラウザ操作の窓口・照会・入力業務」という位置づけの実証として、金融/製造/
不動産に続く4つ目の業種デモ。窓口職員が使う住基・戸籍システムのフロント
（住民異動・証明書交付・戸籍照会）を模したCRUD画面群とし、本体（他の自治体
システムとの連携基盤やLGWANなど）には一切触れない前提を踏襲する。

業務ドメイン対応表（他デモとの対比。main.py側の汎用エンジンを流用するための
「型合わせ」）:
  Customer（顧客）        → Resident（住民）: 住民票上の本人。証明書交付申請の
                            申請対象・内見予約のような明細対象になる「主役」。
  Property/Product        → CertificateTypes（証明書種別カタログ）: 住民票の
  （商品/物件）              写し・戸籍謄本・印鑑登録証明書等、手数料付きの
                            "商品"的ポジション。CertificateRequestの明細行対象。
  Order（受注/契約）      → CertificateRequest（証明書交付申請）: 窓口の主要
                            業務。申請者=Resident、明細行=証明書種別×通数。
  Supplier（仕入先）      → 使用しない（窓口業務に「発注先」は存在しないため
                            本デモでは廃止。他デモとの構造上の差分の一つ）。
  Employee（従業員）      → Employee（窓口職員）: 戸籍住民課の担当職員。
  Estimate（見積）        → Household（世帯）: 世帯構成の照会という、住基業務
                            特有のマスタ照会画面として新設（他デモに対応物なし）。
  InventoryTransaction     → MoveHistory（異動履歴）: 転入/転出/転居/婚姻/出生/
  （在庫トランザクション）    死亡等、住民票上の異動記録。一覧のみ。
  PurchaseOrder/GoodsReceipt→ 使用しない（発注業務が存在しないドメインのため）。
  ArAp/Profit（財務系集計） → 使用しない（窓口業務に売掛買掛・利益概念が
                            馴染まないため、本デモでは意図的に採用しない）。
  （新設）VisitReception   → 来庁受付（整理券）: 来庁者の受付・呼出状況管理。
                            窓口業務特有のワークフロー系エンティティ
                            （dealerのServiceOrder新設と同じ位置づけ）。
  （新設）FamilyRegister   → 戸籍: 本籍・筆頭者ベースの戸籍簿マスタ。
"""
import os
import random
from datetime import datetime, timedelta

import sqlite_store

random.seed(42)

# ---------------------------------------------------------------------------
# 永続化(SQLite)
# ---------------------------------------------------------------------------
_DB_PATH = os.getenv("AISB_KOSEKI_DB_PATH", os.path.join(os.path.dirname(os.path.abspath(__file__)), "koseki.db"))
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
DEPARTMENTS = ["戸籍住民課 戸籍係", "戸籍住民課 住民記録係", "戸籍住民課 証明発行係", "戸籍住民課 総合窓口係"]
POSITIONS = ["課長", "係長", "主任", "主事", "会計年度任用職員"]

RELATIONSHIPS = ["世帯主", "妻", "夫", "長男", "長女", "次男", "次女", "父", "母", "同居人"]
RESIDENT_STATUSES = ["在住", "転出済", "職権消除"]

STREET_NAMES = ["北沢", "梅丘", "代沢", "松原", "羽根木", "桜丘", "経堂", "祖師谷", "成城", "喜多見"]
CITY_NAME = "東京都世田谷区"

CERT_TYPES = [
    {"Id": "CT01", "Name": "住民票の写し", "UnitPrice": 300},
    {"Id": "CT02", "Name": "住民票記載事項証明書", "UnitPrice": 300},
    {"Id": "CT03", "Name": "戸籍謄本（全部事項証明書）", "UnitPrice": 450},
    {"Id": "CT04", "Name": "戸籍抄本（個人事項証明書）", "UnitPrice": 450},
    {"Id": "CT05", "Name": "戸籍の附票の写し", "UnitPrice": 300},
    {"Id": "CT06", "Name": "印鑑登録証明書", "UnitPrice": 300},
    {"Id": "CT07", "Name": "身分証明書", "UnitPrice": 300},
    {"Id": "CT08", "Name": "独身証明書", "UnitPrice": 350},
    {"Id": "CT09", "Name": "改製原戸籍謄本", "UnitPrice": 750},
]

CERT_REQUEST_STATUSES = ["受付", "処理中", "交付済", "却下"]
CERT_REQUEST_USES = ["本人確認", "年金手続き", "パスポート申請", "相続手続き", "融資審査", "婚姻届添付", "その他"]
VISIT_PURPOSES = ["証明書交付", "転入届", "転出届", "転居届", "婚姻届", "出生届", "死亡届", "印鑑登録", "戸籍照会"]
VISIT_STATUSES = ["待機中", "呼出中", "対応中", "完了", "呼出不応答"]
MOVE_TYPES = ["転入", "転出", "転居", "婚姻", "出生", "死亡", "世帯分離", "世帯合併"]
FAMILY_REGISTER_TYPES = ["現在戸籍", "除籍", "改製原戸籍"]


def _rand_date(min_days=-180, max_days=30):
    """base(今日)から見て [min_days, max_days] 日オフセットの日付を返す（負=過去/正=未来）。"""
    base = datetime(2026, 7, 25)
    delta = random.randint(min_days, max_days)
    return (base + timedelta(days=delta)).strftime("%Y-%m-%d")


def _birth_date(min_age=0, max_age=90):
    base = datetime(2026, 7, 25)
    age_days = random.randint(min_age * 365, max_age * 365)
    return (base - timedelta(days=age_days)).strftime("%Y-%m-%d")


def _address():
    return f"{CITY_NAME}{random.choice(STREET_NAMES)}{random.randint(1,5)}-{random.randint(1,20)}-{random.randint(1,10)}"


def _tel():
    return f"0{random.randint(1,9)}-{random.randint(1000,9999)}-{random.randint(1000,9999)}"


def _my_number_masked():
    return f"****-****-{random.randint(1000,9999)}"


# ---------------------------------------------------------------------------
# Households（世帯） — 先に世帯を作り、住民を世帯に所属させる
# ---------------------------------------------------------------------------
households = sqlite_store.PersistentDict(_conn, _lock, "households")
if not households:
    for i in range(1, 15):
        hid = f"H{i:04d}"
        addr = _address()
        households[hid] = {
            "Id": hid,
            "HeadName": "",  # 世帯主決定後に確定させる(下のResident生成後に補完)
            "Address": addr,
            "MemberCount": 0,
            "CreatedAt": _rand_date(-1800, -30),
        }
household_ids = list(households.keys())

# ---------------------------------------------------------------------------
# Residents（住民/住基） — 世帯に所属させ、世帯ごとに1名を世帯主にする
# ---------------------------------------------------------------------------
residents = sqlite_store.PersistentDict(_conn, _lock, "residents")
if not residents:
    idx = 1
    for hid in household_ids:
        hh = households[hid]
        member_count = random.randint(1, 4)
        for m in range(member_count):
            rid = f"R{idx:05d}"
            name, kana, gender = PERSON_NAMES[(idx - 1) % len(PERSON_NAMES)]
            relationship = "世帯主" if m == 0 else random.choice(RELATIONSHIPS[1:])
            residents[rid] = {
                "Id": rid,
                "Name": name,
                "NameKana": kana,
                "Gender": gender,
                "BirthDate": _birth_date(0, 85),
                "Relationship": relationship,
                "HouseholdId": hid,
                "Address": hh["Address"],
                "Tel": _tel() if m == 0 else "",
                "MyNumber": _my_number_masked(),
                "Status": random.choices(RESIDENT_STATUSES, weights=[92, 5, 3])[0],
                "MoveInDate": _rand_date(-1800, -30),
                "Notes": "",
                "CreatedAt": _rand_date(-1800, -30),
            }
            if m == 0:
                hh["HeadName"] = name
            idx += 1
        hh["MemberCount"] = member_count
        households[hid] = hh  # SQLite永続化(dict.update()のインプレース変更はwrite-throughされないため再代入)
resident_ids = list(residents.keys())


def certificate_catalog():
    """CertificateRequest の明細行ピッカー用アダプタ(Id/Name/UnitPriceの形は元々一致)。"""
    return {c["Id"]: c for c in CERT_TYPES}


def resident_options():
    return [(r["Id"], f'{r["Name"]}（{r["Id"]}）') for r in residents.values()]


# ---------------------------------------------------------------------------
# FamilyRegisters（戸籍） — 世帯主を筆頭者とみなす簡易対応
# ---------------------------------------------------------------------------
family_registers = sqlite_store.PersistentDict(_conn, _lock, "family_registers")
if not family_registers:
    for i, hid in enumerate(household_ids, start=1):
        hh = households[hid]
        fid = f"F{i:04d}"
        family_registers[fid] = {
            "Id": fid,
            "HeadName": hh["HeadName"],
            "HonName": hh["Address"],  # 本籍(簡易的に現住所を流用したダミーデータ)
            "RegisterType": random.choices(FAMILY_REGISTER_TYPES, weights=[85, 10, 5])[0],
            "MemberCount": hh["MemberCount"],
            "CompiledDate": _rand_date(-3650, -180),
            "Notes": "",
            "CreatedAt": _rand_date(-3650, -180),
        }
family_register_ids = list(family_registers.keys())

# ---------------------------------------------------------------------------
# Employees（窓口職員）
# ---------------------------------------------------------------------------
employees = sqlite_store.PersistentDict(_conn, _lock, "employees")
if not employees:
    for i in range(1, 13):
        eid = f"E{i:03d}"
        name, _, _ = PERSON_NAMES[(i - 1) % len(PERSON_NAMES)]
        employees[eid] = {
            "Id": eid,
            "Name": name,
            "Department": random.choice(DEPARTMENTS),
            "Position": random.choice(POSITIONS),
            "CounterNo": f"{random.randint(1,8)}番窓口",
            "Email": f"staff{i:03d}@city-koseki-legacy.example.jp",
            "Tel": _tel(),
            "HireDate": _rand_date(-5000, -100),
            "CreatedAt": _rand_date(-5000, -100),
        }
employee_ids = list(employees.keys())

# ---------------------------------------------------------------------------
# CertificateRequests（証明書交付申請） + CertificateRequestItems（明細行）
# 元ERPのOrderに相当。申請者=Resident、明細行=証明書種別×通数。
# ---------------------------------------------------------------------------
certificate_requests = sqlite_store.PersistentDict(_conn, _lock, "certificate_requests")
certificate_request_items = sqlite_store.PersistentDict(_conn, _lock, "certificate_request_items")
if not certificate_requests:
    for i in range(1, 34):
        cid = f"CR{1000 + i}"
        applicant = residents[random.choice(resident_ids)]
        items = []
        for _ in range(random.randint(1, 3)):
            ct = random.choice(CERT_TYPES)
            qty = random.randint(1, 3)
            items.append({"ProductId": ct["Id"], "ProductName": ct["Name"], "Quantity": qty,
                          "UnitPrice": ct["UnitPrice"], "Amount": qty * ct["UnitPrice"]})
        total = sum(it["Amount"] for it in items)
        req_date = _rand_date(-120, 0)
        certificate_requests[cid] = {
            "Id": cid,
            "CustomerId": applicant["Id"],
            "CustomerName": applicant["Name"],
            "OrderDate": req_date,
            "DeliveryDate": req_date,  # 窓口即日交付が基本のため申請日=交付予定日
            "TotalAmount": total,
            "Status": random.choice(CERT_REQUEST_STATUSES),
            "Purpose": random.choice(CERT_REQUEST_USES),
            "Notes": "",
            "CreatedAt": req_date,
        }
        certificate_request_items[cid] = items
certificate_request_ids = list(certificate_requests.keys())

# ---------------------------------------------------------------------------
# VisitReceptions（来庁受付/整理券） — ワークフロー色の強い新設エンティティ
# ---------------------------------------------------------------------------
visit_receptions = sqlite_store.PersistentDict(_conn, _lock, "visit_receptions")
if not visit_receptions:
    for i in range(1, 41):
        vid = f"VR{1000 + i}"
        visitor = residents[random.choice(resident_ids)]
        staff = employees[random.choice(employee_ids)] if random.random() > 0.15 else None
        visit_receptions[vid] = {
            "Id": vid,
            "VisitorName": visitor["Name"],
            "VisitorId": visitor["Id"],
            "Purpose": random.choice(VISIT_PURPOSES),
            "ReceptionTime": _rand_date(-14, 0),
            "CounterNo": staff["CounterNo"] if staff else "",
            "EmployeeId": staff["Id"] if staff else "",
            "EmployeeName": staff["Name"] if staff else "未割当",
            "Status": random.choice(VISIT_STATUSES),
            "Notes": "",
            "CreatedAt": _rand_date(-14, 0),
        }
visit_reception_ids = list(visit_receptions.keys())

# ---------------------------------------------------------------------------
# MoveHistory（異動履歴） — 元ERPのInventoryTransactionに相当。一覧のみ。
# ---------------------------------------------------------------------------
move_history = sqlite_store.PersistentList(_conn, _lock, "move_history")
if not move_history:
    for i in range(1, 61):
        rid = random.choice(resident_ids)
        r = residents[rid]
        move_history.append({
            "Id": f"MV{i:05d}",
            "ProductId": rid,
            "ProductName": r["Name"],
            "Type": random.choice(MOVE_TYPES),
            "Date": _rand_date(-720, 0),
            "Notes": "",
        })
# main.py 側は元ERPと同じ変数名(inventory_transactions)で参照するためのエイリアス。
inventory_transactions = move_history


# ---------------------------------------------------------------------------
# ID採番（新規登録用）
# ---------------------------------------------------------------------------
_counters = {
    "Resident": len(residents), "Household": len(households), "FamilyRegister": len(family_registers),
    "Employee": len(employees), "CertificateRequest": len(certificate_requests),
    "VisitReception": len(visit_receptions),
}
_ID_FORMATS = {
    "Resident": "R{:05d}", "Household": "H{:04d}", "FamilyRegister": "F{:04d}",
    "Employee": "E{:03d}", "CertificateRequest": "CR{:04d}", "VisitReception": "VR{:04d}",
}


def next_id(entity: str) -> str:
    _counters[entity] += 1
    n = _counters[entity]
    fmt = _ID_FORMATS[entity]
    # CR/VRは元データが1000番台始まりなので揃える
    if entity in ("CertificateRequest", "VisitReception"):
        return fmt.format(1000 + n)
    return fmt.format(n)
