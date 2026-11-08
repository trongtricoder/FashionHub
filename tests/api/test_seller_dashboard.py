"""Test API dashboard, gợi ý và hỏi đáp của Seller bằng Supabase giả (cố định ngày hôm nay)."""
from datetime import date, datetime, timedelta, timezone

import pytest

from api.index import create_app
from api.routes import ai as ai_routes
from api.routes import seller_dashboard as dashboard_routes
from api.services import auth as auth_service
from api.services import seller_data
from tests.api.fake_db import FakeDB

S1 = {"Authorization": "Bearer tok-s1"}
S2 = {"Authorization": "Bearer tok-s2"}
BUYER = {"Authorization": "Bearer tok-buyer"}
NO_SHOP = {"Authorization": "Bearer tok-s3"}
TODAY = date(2026, 10, 30)   # thứ Sáu


def at(day, hour=12):
    """Mốc UTC ứng với giờ `hour` (giờ Việt Nam) của ngày `day`."""
    local = datetime(day.year, day.month, day.day, hour, tzinfo=timezone(timedelta(hours=7)))
    return local.astimezone(timezone.utc).isoformat()


def ago(n):
    return TODAY - timedelta(days=n)


def build_tables():
    events = []
    # 2500 lượt xem trong 30 ngày (nhiều hơn 1000 để kiểm tra phân trang), 25 lượt mỗi ngày cho 100 ngày gần nhất
    for n in range(100):
        for _ in range(25):
            events.append({"shop_id": 1, "product_id": 1, "event_type": "view", "created_at": at(ago(n), 10)})
    events.append({"shop_id": 1, "product_id": 1, "event_type": "view", "created_at": "2026-10-29T17:30:00+00:00"})  # 00:30 ngày 30
    events.append({"shop_id": 2, "product_id": 3, "event_type": "view", "created_at": at(TODAY)})                    # shop khác
    events.append({"shop_id": 1, "product_id": 1, "event_type": "add_to_cart", "created_at": at(TODAY)})             # không phải lượt xem
    events.append({"shop_id": 1, "product_id": 2, "event_type": "purchase", "created_at": at(TODAY)})

    orders, items, oid = [], [], 0

    def order(status, day, total, buyer="u-b1", shop=1, variant=1, product=1, qty=1):
        nonlocal oid
        oid += 1
        orders.append({"id": oid, "shop_id": shop, "buyer_id": buyer, "status": status, "total": total,
                       "created_at": at(day, 9), "updated_at": at(day, 15)})
        items.append({"id": oid, "order_id": oid, "variant_id": variant, "product_id": product, "quantity": qty})

    for n in range(30):                                  # mỗi ngày một đơn hoàn tất 1 triệu của shop 1
        order("completed", ago(n), 1000000)
    order("completed", ago(5), 500000, variant=2, product=2, qty=3)      # thêm một đơn trong tuần
    order("completed", ago(45), 777000)                                  # ngoài 30 ngày
    order("cancelled", ago(2), 999999)                                   # đã hủy: không tính doanh thu
    order("pending", ago(1), 200000, buyer="u-b2", variant=2, product=2, qty=2)
    order("completed", ago(1), 424242, shop=2, variant=3, product=3)     # shop khác

    return {
        "profiles": [
            {"id": "u-s1", "role": "seller", "status": "active"}, {"id": "u-s2", "role": "seller", "status": "active"},
            {"id": "u-s3", "role": "seller", "status": "active"}, {"id": "u-buyer", "role": "buyer", "status": "active"},
            {"id": "u-b1", "role": "buyer", "status": "active"}, {"id": "u-b2", "role": "buyer", "status": "active"},
        ],
        "shops": [{"id": 1, "owner_id": "u-s1", "name": "Shop A"}, {"id": 2, "owner_id": "u-s2", "name": "Shop B"}],
        "products": [
            {"id": 1, "shop_id": 1, "name": "Áo thun basic", "sold_count": 30, "moderation_status": "approved", "is_active": True},
            {"id": 2, "shop_id": 1, "name": "Quần jeans", "sold_count": 5, "moderation_status": "approved", "is_active": True},
            {"id": 3, "shop_id": 2, "name": "Váy dài", "sold_count": 1, "moderation_status": "approved", "is_active": True},
        ],
        "product_variants": [
            {"id": 1, "product_id": 1, "size": "M", "color": "Trắng", "stock": 3},     # sắp hết mà đang bán chạy
            {"id": 2, "product_id": 2, "size": "L", "color": "Đen", "stock": 40},
            {"id": 3, "product_id": 3, "size": "S", "color": "Hồng", "stock": 9},
        ],
        "orders": orders, "order_items": items, "analytics_events": events,
        "body_profiles": [{"user_id": "u-b1", "body_shape": "pear"}, {"user_id": "u-b2", "body_shape": "pear"}],
    }


@pytest.fixture
def db():
    return FakeDB(build_tables(), {"tok-s1": "u-s1", "tok-s2": "u-s2", "tok-s3": "u-s3", "tok-buyer": "u-buyer"})


@pytest.fixture
def client(db, monkeypatch):
    for module in (dashboard_routes, ai_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    monkeypatch.setattr(seller_data, "today_vn", lambda: TODAY)
    return create_app().test_client()


def dash(client, range_key="30d", headers=S1):
    return client.get(f"/api/seller/dashboard?range={range_key}", headers=headers)


# ---------- quyền và tham số ----------

def test_chi_seller_moi_xem_duoc(client):
    assert client.get("/api/seller/dashboard").status_code == 401
    assert dash(client, headers=BUYER).status_code == 403
    assert client.post("/api/ai/seller/insights", headers=BUYER).status_code == 403
    assert client.post("/api/ai/seller/chat", json={"message": "x"}, headers=BUYER).status_code == 403


def test_khoang_thoi_gian_sai_va_chua_co_shop(client):
    assert dash(client, "1y").status_code == 400
    assert dash(client, headers=NO_SHOP).status_code == 404
    assert client.post("/api/ai/seller/insights", headers=NO_SHOP).status_code == 404


# ---------- dashboard ----------

def test_dashboard_30_ngay_dem_du_tren_1000_luot_xem(client):
    data = dash(client).get_json()["data"]
    assert data["range"] == "30d" and len(data["labels"]) == 30 and data["labels"][-1] == "2026-10-30"
    # 30 ngày x 25 lượt + 1 lượt lúc 00:30 giờ Việt Nam của ngày 30 = 751; nếu quên phân trang sẽ chỉ còn 1000 dòng đầu
    assert data["kpi"]["total_views"] == 30 * 25 + 1
    assert data["views"][-1] == 26 and data["views"][0] == 25


def test_dashboard_doanh_thu_theo_ngay_hoan_tat(client):
    data = dash(client).get_json()["data"]
    assert data["revenue"][-1] == 1000000 and data["revenue"][-6] == 1500000      # ngày 25/10 có thêm đơn 500.000
    assert data["kpi"]["total_revenue"] == 30 * 1000000 + 500000                   # không tính đơn hủy, đơn cũ, đơn shop khác
    assert data["kpi"]["total_orders"] == 31
    assert data["kpi"]["conversion_rate"] == round(31 / 751, 4)
    assert data["kpi"]["total_sold"] == 35 and data["kpi"]["total_stock"] == 43


def test_dashboard_7_ngay_va_du_doan(client):
    data = dash(client, "7d").get_json()["data"]
    assert len(data["labels"]) == 7 and data["kpi"]["total_views"] == 7 * 25 + 1
    forecast = data["forecast"]
    assert forecast["labels"][0] == "2026-10-31" and len(forecast["revenue"]) == 7
    assert all(isinstance(v, int) and v >= 0 for v in forecast["revenue"])
    assert abs(forecast["revenue"][0] - 1000000) < 150000                           # doanh thu đều nên dự đoán quanh 1 triệu


def test_dashboard_12_thang_khong_du_doan(client):
    data = dash(client, "12m").get_json()["data"]
    assert len(data["labels"]) == 12 and data["labels"][-1] == "2026-10" and data["forecast"] is None
    assert data["kpi"]["total_views"] == 100 * 25 + 1                                # 100 ngày dữ liệu, vượt xa 1000 dòng
    assert data["views"][-1] == 30 * 25 + 1 and data["views"][-2] == 30 * 25          # tháng 10 (30 ngày + 1 lượt) và tháng 9


def test_dashboard_khong_lan_du_lieu_shop_khac(client):
    other = dash(client, "30d", S2).get_json()["data"]
    assert other["kpi"]["total_views"] == 1 and other["kpi"]["total_revenue"] == 424242


# ---------- gợi ý ----------

def test_goi_y_tu_du_lieu_that(client):
    data = client.post("/api/ai/seller/insights", headers=S1).get_json()["data"]
    titles = [s["title"] for s in data["suggestions"]]
    assert "Nên nhập thêm Áo thun basic (size M, màu Trắng)" in titles          # còn 3 mà tuần qua có bán
    assert any(t.startswith("Đẩy mạnh sản phẩm bán chạy") for t in titles)
    assert "Nhập thêm đồ hợp dáng quả lê" in titles                               # cả 2 người mua đều dáng quả lê
    assert data["suggestions"][0]["severity"] == "warning" and data["summary"]


def test_goi_y_chi_tinh_don_chua_huy(client):
    top = next(s for s in client.post("/api/ai/seller/insights", headers=S1).get_json()["data"]["suggestions"]
               if s["title"].startswith("Đẩy mạnh"))["detail"]
    assert "Áo thun basic (30)" in top and "Quần jeans (5)" in top                # 3 + 2 của đơn đang chờ, bỏ đơn hủy


# ---------- hỏi đáp ----------

def chat(client, message, headers=S1):
    return client.post("/api/ai/seller/chat", json={"message": message}, headers=headers)


def test_hoi_doanh_thu_tra_loi_bang_so_that(client):
    reply = chat(client, "Doanh thu tuần này?").get_json()["data"]["reply"]
    assert "7.500.000đ" in reply and "30.500.000đ" in reply                      # 7 ngày: 7 triệu + 500k, 30 ngày: 30 triệu + 500k


def test_hoi_ton_kho_va_don_hang(client):
    assert "Áo thun basic (M, Trắng): còn 3" in chat(client, "tồn kho còn bao nhiêu").get_json()["data"]["reply"]
    orders_reply = chat(client, "đơn hàng của tôi").get_json()["data"]["reply"]
    assert "1 chờ xác nhận" in orders_reply and "32 hoàn tất" in orders_reply and "1 đã hủy" in orders_reply


def test_hoi_dap_kiem_tra_dau_vao(client):
    assert chat(client, "   ").status_code == 400
    assert chat(client, "x" * 301).status_code == 400
    assert client.post("/api/ai/seller/chat", json={}, headers=S1).status_code == 400
    assert "Mình chưa hiểu" in chat(client, "blah").get_json()["data"]["reply"]