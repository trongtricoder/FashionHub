"""Test phía Seller: đơn hàng, đổi trạng thái (kho, sold_count, sự kiện), thống kê."""
import pytest

from api.index import create_app
from api.routes import seller as seller_routes
from api.services import auth as auth_service
from tests.api.fake_db import FakeDB

S1 = {"Authorization": "Bearer tok-seller1"}
S2 = {"Authorization": "Bearer tok-seller2"}
BUYER = {"Authorization": "Bearer tok-buyer"}


def order_row(oid, shop_id, status, payment="cod", paid="unpaid"):
    return {"id": oid, "buyer_id": "u-buyer", "shop_id": shop_id, "total": 300000, "status": status,
            "payment_method": payment, "payment_status": paid, "receiver_name": "Lan", "phone": "0988123456",
            "address": "Quận 1", "lat": 10.77, "lng": 106.70, "eta_minutes": 40,
            "created_at": f"2026-10-2{oid}T03:00:00+00:00", "updated_at": "2026-10-28T03:00:00+00:00"}


@pytest.fixture
def db():
    return FakeDB(
        {
            "profiles": [
                {"id": "u-buyer", "role": "buyer", "status": "active", "username": "buyer1", "full_name": "Nguyễn Thị Lan", "phone": "0900000011"},
                {"id": "u-s1", "role": "seller", "status": "active", "username": "seller1"},
                {"id": "u-s2", "role": "seller", "status": "active", "username": "seller2"},
            ],
            "shops": [
                {"id": 1, "owner_id": "u-s1", "name": "Shop A", "lat": 10.76, "lng": 106.66, "prep_minutes": 30, "address": "A"},
                {"id": 2, "owner_id": "u-s2", "name": "Shop B", "lat": 10.73, "lng": 106.72, "prep_minutes": 45, "address": "B"},
            ],
            "products": [
                {"id": 1, "shop_id": 1, "name": "Áo thun basic", "price": 150000, "sold_count": 4, "moderation_status": "approved", "is_active": True},
                {"id": 2, "shop_id": 1, "name": "Hàng chờ duyệt", "price": 99000, "sold_count": 0, "moderation_status": "pending", "is_active": True},
                {"id": 3, "shop_id": 2, "name": "Quần jeans", "price": 380000, "sold_count": 0, "moderation_status": "approved", "is_active": True},
            ],
            "product_variants": [
                {"id": 1, "product_id": 1, "size": "M", "color": "Trắng", "stock": 5},
                {"id": 2, "product_id": 1, "size": "L", "color": "Trắng", "stock": 20},
                {"id": 3, "product_id": 3, "size": "M", "color": "Đen", "stock": 10},
                {"id": 4, "product_id": 2, "size": "M", "color": "Đen", "stock": 1},
            ],
            "product_images": [{"product_id": 1, "url": "https://img/a.jpg", "is_main": True, "position": 0}],
            "orders": [
                order_row(1, 1, "pending"),
                order_row(2, 1, "processing"),
                order_row(3, 1, "shipping"),
                order_row(4, 1, "completed", paid="paid"),
                order_row(5, 2, "pending"),
            ],
            "order_items": [
                {"id": 1, "order_id": 1, "variant_id": 1, "product_id": 1, "product_name": "Áo thun basic", "size": "M", "color": "Trắng", "quantity": 2, "price": 150000},
                {"id": 2, "order_id": 2, "variant_id": 2, "product_id": 1, "product_name": "Áo thun basic", "size": "L", "color": "Trắng", "quantity": 3, "price": 150000},
                {"id": 3, "order_id": 3, "variant_id": 1, "product_id": 1, "product_name": "Áo thun basic", "size": "M", "color": "Trắng", "quantity": 1, "price": 150000},
                {"id": 4, "order_id": 4, "variant_id": 2, "product_id": 1, "product_name": "Áo thun basic", "size": "L", "color": "Trắng", "quantity": 1, "price": 150000},
                {"id": 5, "order_id": 5, "variant_id": 3, "product_id": 3, "product_name": "Quần jeans", "size": "M", "color": "Đen", "quantity": 1, "price": 380000},
            ],
            "analytics_events": [],
        },
        {"tok-seller1": "u-s1", "tok-seller2": "u-s2", "tok-buyer": "u-buyer"},
    )


@pytest.fixture
def client(db, monkeypatch):
    for module in (seller_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    return create_app().test_client()


def stock(db, variant_id):
    return next(v["stock"] for v in db.tables["product_variants"] if v["id"] == variant_id)


def put_status(client, oid, status, headers=S1):
    return client.patch(f"/api/seller/orders/{oid}/status", json={"status": status}, headers=headers)


# ---------- quyền và xem đơn ----------

def test_chi_seller_moi_vao_duoc(client):
    assert client.get("/api/seller/orders").status_code == 401
    assert client.get("/api/seller/orders", headers=BUYER).status_code == 403
    assert client.get("/api/seller/stats", headers=BUYER).status_code == 403


def test_xem_shop_cua_minh(client):
    assert client.get("/api/seller/shop", headers=S1).get_json()["data"]["name"] == "Shop A"
    assert client.get("/api/seller/shop", headers=S2).get_json()["data"]["name"] == "Shop B"


def test_chi_thay_don_cua_shop_minh_kem_nguoi_mua(client):
    items = client.get("/api/seller/orders", headers=S1).get_json()["data"]["items"]
    assert sorted(o["id"] for o in items) == [1, 2, 3, 4]       # đơn 5 của shop B không hiện
    first = next(o for o in items if o["id"] == 1)
    assert first["buyer"] == {"name": "Nguyễn Thị Lan", "phone": "0900000011"}
    assert first["items"][0]["image_url"] == "https://img/a.jpg" and first["distance_km"] is not None


def test_loc_theo_trang_thai(client):
    def ids(q):
        return sorted(o["id"] for o in client.get(f"/api/seller/orders?status={q}", headers=S1).get_json()["data"]["items"])
    assert ids("pending") == [1] and ids("processing") == [2] and ids("shipping") == [3] and ids("history") == [4]
    assert client.get("/api/seller/orders?status=abc", headers=S1).status_code == 400


# ---------- đổi trạng thái ----------

def test_xac_nhan_don_tru_ton_kho(client, db):
    res = put_status(client, 1, "processing")
    assert res.status_code == 200 and res.get_json()["data"]["status"] == "processing"
    assert stock(db, 1) == 3  # 5 - 2


def test_thieu_hang_thi_khong_xac_nhan_duoc(client, db):
    db.tables["product_variants"][0]["stock"] = 1   # đơn cần 2
    res = put_status(client, 1, "processing")
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "OUT_OF_STOCK"
    assert stock(db, 1) == 1
    assert next(o for o in db.tables["orders"] if o["id"] == 1)["status"] == "pending"


def test_huy_don_dang_xu_ly_hoan_ton_kho(client, db):
    assert put_status(client, 2, "cancelled").status_code == 200
    assert stock(db, 2) == 23  # 20 + 3


def test_huy_don_cho_xac_nhan_khong_dong_den_kho(client, db):
    assert put_status(client, 1, "cancelled").status_code == 200
    assert stock(db, 1) == 5


def test_hoan_tat_ghi_sold_count_su_kien_va_thanh_toan(client, db):
    res = put_status(client, 3, "completed")
    assert res.status_code == 200 and res.get_json()["data"]["payment_status"] == "paid"
    assert next(p for p in db.tables["products"] if p["id"] == 1)["sold_count"] == 5  # 4 + 1
    events = db.tables["analytics_events"]
    assert len(events) == 1 and events[0]["event_type"] == "purchase" and events[0]["user_id"] == "u-buyer"


def test_seller_khong_the_tu_danh_dau_chuyen_khoan_la_da_thanh_toan(client, db):
    db.tables["orders"].append(order_row(6, 1, "shipping", payment="bank_transfer", paid="reported"))
    response = put_status(client, 6, "completed")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "PAYMENT_NOT_CONFIRMED"
    order = next(order for order in db.tables["orders"] if order["id"] == 6)
    assert order["status"] == "shipping" and order["payment_status"] == "reported"


def test_seller_khong_the_bat_dau_xu_ly_don_chuyen_khoan_chua_doi_soat(client, db):
    db.tables["orders"].append(order_row(6, 1, "pending", payment="bank_transfer", paid="unpaid"))
    response = put_status(client, 6, "processing")
    assert response.status_code == 409
    assert response.get_json()["error"]["code"] == "PAYMENT_NOT_CONFIRMED"
    assert next(order for order in db.tables["orders"] if order["id"] == 6)["status"] == "pending"


def test_ca_vong_doi_cua_mot_don(client, db):
    for status in ("processing", "shipping", "completed"):
        assert put_status(client, 1, status).status_code == 200
    assert stock(db, 1) == 3 and next(p for p in db.tables["products"] if p["id"] == 1)["sold_count"] == 6


@pytest.mark.parametrize("oid,new", [
    (1, "completed"), (1, "shipping"), (2, "pending"), (3, "cancelled"),
    (4, "processing"), (4, "cancelled"), (2, "processing"),
])
def test_chuyen_sai_luat_tra_422(client, db, oid, new):
    res = put_status(client, oid, new)
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "INVALID_STATE"


def test_bam_hai_lan_lan_hai_bi_chan(client, db):
    assert put_status(client, 1, "processing").status_code == 200
    assert put_status(client, 1, "processing").status_code == 422
    assert stock(db, 1) == 3  # chỉ trừ một lần


def test_khong_dung_duoc_don_cua_shop_khac(client, db):
    assert put_status(client, 5, "processing").status_code == 404   # seller1 đụng đơn shop B
    assert put_status(client, 1, "processing", headers=S2).status_code == 404
    assert put_status(client, 999, "processing").status_code == 404


def test_trang_thai_khong_hop_le(client):
    assert put_status(client, 1, "abc").status_code == 400
    assert client.patch("/api/seller/orders/1/status", json={}, headers=S1).status_code == 400


def test_don_mat_bien_the_thi_khong_xac_nhan(client, db):
    db.tables["order_items"][0]["variant_id"] = None   # biến thể đã bị xóa
    res = put_status(client, 1, "processing")
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "PRODUCT_UNAVAILABLE"


def test_xung_dot_ton_kho_thi_hoan_lai_phan_da_tru(client, db, monkeypatch):
    """Giả lập người khác sửa tồn kho giữa lúc đọc và lúc ghi: không được trừ chồng, không mất hàng."""
    from api.services import fulfillment
    original = fulfillment.fetch_by_ids

    def stale(db_, table, ids, columns="*"):
        rows = original(db_, table, ids, columns)
        if table == "product_variants":
            db.tables["product_variants"][0]["stock"] = 4  # sau khi đọc xong, người khác đổi 5 thành 4
        return rows

    monkeypatch.setattr(fulfillment, "fetch_by_ids", stale)
    res = put_status(client, 1, "processing")
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "STOCK_CONFLICT"
    assert stock(db, 1) == 4
    assert next(o for o in db.tables["orders"] if o["id"] == 1)["status"] == "pending"


# ---------- thống kê ----------

def test_thong_ke_shop(client):
    data = client.get("/api/seller/stats", headers=S1).get_json()["data"]
    assert data["orders_by_status"] == {"pending": 1, "processing": 1, "shipping": 1, "completed": 1, "cancelled": 0}
    assert data["total_stock"] == 5 + 20 + 1
    assert data["total_sold"] == 4
    assert data["pending_products"] == 1
    # sắp hết hàng: chỉ sản phẩm đã duyệt, tồn <= 5 (biến thể của hàng chờ duyệt không tính)
    assert data["low_stock"] == [{"product_id": 1, "name": "Áo thun basic", "size": "M", "color": "Trắng", "stock": 5}]