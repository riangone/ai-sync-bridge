"""
デモ・レガシーシステム (localhost:5010)
AI機能ゼロの模擬ERP。WebForms風の古い見た目の顧客/受注管理。
AI-Sync Bridge の Chrome拡張がこのDOM上にサイドバーを注入する「未改変ターゲット」。
このプロセスは ai-api-server (5011) とは完全に独立している。
"""
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, Form, HTTPException
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

BASE_DIR = Path(__file__).parent
STATIC_DIR = BASE_DIR / "static"

app = FastAPI(title="Legacy ERP System (Demo)")

# ---- 超簡易インメモリ「レガシーDB」----
_next_id = 4
customers_db: dict[int, dict] = {
    1: {"id": 1, "name": "山田太郎", "company": "山田商事", "phone": "03-1234-5678", "status": "取引中"},
    2: {"id": 2, "name": "佐藤花子", "company": "佐藤工業", "phone": "03-2345-6789", "status": "取引中"},
    3: {"id": 3, "name": "鈴木一郎", "company": "鈴木商店", "phone": "03-3456-7890", "status": "休止"},
}
orders_db: list[dict] = [
    {"id": 1001, "customer_id": 1, "item": "産業用ポンプ A-100", "qty": 5, "amount": 1250000, "date": "2026-06-01"},
    {"id": 1002, "customer_id": 2, "item": "制御盤 CB-220", "qty": 2, "amount": 890000, "date": "2026-06-15"},
    {"id": 1003, "customer_id": 1, "item": "メンテナンス契約", "qty": 1, "amount": 300000, "date": "2026-07-01"},
]


# ---- レガシー画面 (素のHTML) ----
@app.get("/")
def root():
    return RedirectResponse(url="/pages/customers.html")


app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


@app.get("/pages/{page_name}")
def serve_page(page_name: str):
    path = STATIC_DIR / "pages" / page_name
    if not path.exists():
        raise HTTPException(404, "Page not found")
    return FileResponse(path)


# ---- レガシー「業務API」(実際の古いシステムはこれがASP.NET WebForms等) ----
@app.get("/legacy-api/customers")
def list_customers():
    return list(customers_db.values())


@app.get("/legacy-api/customers/{customer_id}")
def get_customer(customer_id: int):
    c = customers_db.get(customer_id)
    if not c:
        raise HTTPException(404, "Customer not found")
    return c


@app.post("/legacy-api/customers")
def create_customer(name: str = Form(...), company: str = Form(""), phone: str = Form(""), status: str = Form("取引中")):
    global _next_id
    cid = _next_id
    _next_id += 1
    customers_db[cid] = {"id": cid, "name": name, "company": company, "phone": phone, "status": status}
    return RedirectResponse(url="/pages/customers.html", status_code=303)


@app.get("/legacy-api/orders")
def list_orders():
    enriched = []
    for o in orders_db:
        c = customers_db.get(o["customer_id"], {})
        enriched.append({**o, "customer_name": c.get("name", "不明")})
    return enriched


@app.post("/legacy-api/orders")
def create_order(customer_id: int = Form(...), item: str = Form(...), qty: int = Form(...), amount: int = Form(...)):
    new_id = max((o["id"] for o in orders_db), default=1000) + 1
    orders_db.append({
        "id": new_id, "customer_id": customer_id, "item": item, "qty": qty,
        "amount": amount, "date": datetime.utcnow().strftime("%Y-%m-%d"),
    })
    return RedirectResponse(url="/pages/orders.html", status_code=303)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="0.0.0.0", port=5010, reload=True)
