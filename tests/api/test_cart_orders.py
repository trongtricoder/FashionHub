"""Test giỏ hàng, đặt hàng, hủy đơn, ghi sự kiện bằng Supabase giả."""
import pytest

from api.index import create_app
from api.routes import cart as cart_routes
from api.routes import events as events_routes
from api.routes import orders as orders_routes
from api.services import auth as auth_service
from tests.api.fake_db import FakeDB

BUYER = {"Authorization": "Bearer tok-buyer"}
OTHER = {"Authorization": "Bearer tok-other"}
SELLER = {"Authorization": "Bearer tok-seller"}

SHOP_1 = {"id": 1, "name": "Shop A", "lat": 10.7769, "lng": 106.7009, "prep_minutes": 30, "address": "A"}
SHOP_2 = {"id": 2, "name": "Shop B", "lat": 10.7340, "lng": 106.7220, "prep_minutes": 45, "address": "B"}


def make_product(pid, shop_id, name, price, status="approved", active=True):
    return {"id": pid, "name": name, "description": f"Mô tả {name} đủ dài", "price": price,
            "category": "ao", "sold_count": 0, "created_at": "2026-10-01", "shop_id": shop_id,
            "moderation_status": status, "is_active": active}


@pytest.fixture
def db():
    return FakeDB(
        {
            "profiles": [
                {"id": "u-buyer", "role": "buyer", "status": "active", "username": "buyer1"},
                {"id": "u-other", "role": "buyer", "status": "active", "username": "buyer2"},
                {"id": "u-seller", "role": "seller", "status": "active", "username": "seller1"},
            ],
            "shops": [SHOP_1, SHOP_2],
            "products": [
                make_product(1, 1, "Áo thun basic", 150000),
                make_product(2, 2, "Quần jeans", 380000),
                make_product(3, 1, "Hàng bị chặn", 99000, status="blocked"),
            ],
            "product_variants": [
                {"id": 1, "product_id": 1, "size": "M", "color": "Trắng", "stock": 5},
                {"id": 2, "product_id": 1, "size": "L", "color": "Trắng", "stock": 0},
                {"id": 3, "product_id": 2, "size": "M", "color": "Đen", "stock": 10},
                {"id": 4, "product_id": 3, "size": "M", "color": "Đen", "stock": 9},
            ],
            "product_images": [
                {"product_id": 1, "url": "https://img/a.jpg", "is_main": True, "position": 0},
                {"product_id": 2, "url": "https://img/b.jpg", "is_main": True, "position": 0},
            ],
            "reviews": [{"product_id": 1, "rating": 5}],
            "analytics_events": [],
        },
        {"tok-buyer": "u-buyer", "tok-other": "u-other", "tok-seller": "u-seller"},
    )


@pytest.fixture
def client(db, monkeypatch):
    for module in (cart_routes, orders_routes, events_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    return create_app().test_client()


def add(client, variant_id, quantity, headers=BUYER):
    return client.post("/api/cart/items", json={"variant_id": variant_id, "quantity": quantity}, headers=headers)


CHECKOUT = {"receiver_name": "Lan", "phone": "0988123456", "address": "12 Nguyễn Huệ, Quận 1",
            "payment_method": "cod"}


# ---------- giỏ hàng ----------

def test_gio_hang_can_dang_nhap_va_dung_vai_tro(client):
    assert client.get("/api/cart").status_code == 401
    assert client.get("/api/cart", headers=SELLER).status_code == 403


def test_them_vao_gio_va_cong_don(client):
    first = add(client, 1, 2)
    assert first.status_code == 201 and first.get_json()["data"]["quantity"] == 2
    second = add(client, 1, 1)
    assert second.status_code == 200 and second.get_json()["data"]["quantity"] == 3


def test_vuot_ton_kho_tra_409(client):
    add(client, 1, 4)
    res = add(client, 1, 2)  # 4 + 2 > 5
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "OUT_OF_STOCK"
    assert add(client, 3, 1).status_code == 201  # biến thể khác còn hàng vẫn thêm được
    assert add(client, 2, 1).status_code == 409  # biến thể hết hàng (stock 0)


def test_them_san_pham_khong_ban_hoac_khong_ton_tai(client):
    assert add(client, 4, 1).get_json()["error"]["code"] == "PRODUCT_UNAVAILABLE"
    assert add(client, 999, 1).status_code == 404
    assert add(client, 1, 0).status_code == 400
    assert add(client, 1, 100).status_code == 400


def test_xem_gio_co_tong_tien(client):
    add(client, 1, 2)
    add(client, 3, 1)
    data = client.get("/api/cart", headers=BUYER).get_json()["data"]
    assert data["total"] == 150000 * 2 + 380000
    first = data["items"][0]
    assert first["product"]["shop_name"] == "Shop A" and first["product"]["image_url"] == "https://img/a.jpg"
    assert first["size"] == "M" and first["stock"] == 5 and first["available"] is True


def test_sua_va_xoa_dong_gio(client):
    item_id = add(client, 1, 1).get_json()["data"]["id"]
    assert client.patch(f"/api/cart/items/{item_id}", json={"quantity": 9}, headers=BUYER).status_code == 409
    assert client.patch(f"/api/cart/items/{item_id}", json={"quantity": 3}, headers=BUYER).get_json()["data"]["quantity"] == 3
    assert client.patch(f"/api/cart/items/{item_id}", json={"quantity": 0}, headers=BUYER).status_code == 400
    assert client.delete(f"/api/cart/items/{item_id}", headers=BUYER).status_code == 200
    assert client.get("/api/cart", headers=BUYER).get_json()["data"]["items"] == []


def test_khong_dung_duoc_gio_cua_nguoi_khac(client):
    item_id = add(client, 1, 1).get_json()["data"]["id"]
    assert client.patch(f"/api/cart/items/{item_id}", json={"quantity": 2}, headers=OTHER).status_code == 404
    assert client.delete(f"/api/cart/items/{item_id}", headers=OTHER).status_code == 404


# ---------- đặt hàng ----------

def test_checkout_tach_don_theo_shop(client, db):
    a = add(client, 1, 2).get_json()["data"]["id"]
    b = add(client, 3, 1).get_json()["data"]["id"]
    res = client.post("/api/orders/checkout", headers=BUYER, json=dict(
        CHECKOUT, cart_item_ids=[a, b], payment_method="mock_card", lat=10.7726, lng=106.6679))
    assert res.status_code == 201
    orders = res.get_json()["data"]["orders"]
    assert [o["shop_name"] for o in orders] == ["Shop A", "Shop B"]
    assert [o["total"] for o in orders] == [300000, 380000]
    assert all(o["payment_status"] == "paid" and o["status"] == "pending" for o in orders)
    assert all(o["eta_minutes"] is not None and o["expected_at"] and o["distance_km"] for o in orders)
    assert orders[0]["items"][0]["image_url"] == "https://img/a.jpg"
    assert orders[0]["items_summary"] == "Áo thun basic x2"
    assert len(db.tables["order_items"]) == 2
    assert db.tables["cart_items"] == []  # đã xóa mục đặt khỏi giỏ


def test_checkout_khong_co_toa_do_thi_eta_null(client):
    a = add(client, 1, 1).get_json()["data"]["id"]
    order = client.post("/api/orders/checkout", headers=BUYER, json=dict(CHECKOUT, cart_item_ids=[a])).get_json()["data"]["orders"][0]
    assert order["eta_minutes"] is None and order["expected_at"] is None and order["distance_km"] is None
    assert order["payment_status"] == "unpaid"


def test_checkout_chi_dat_dong_duoc_chon(client, db):
    a = add(client, 1, 1).get_json()["data"]["id"]
    add(client, 3, 1)
    client.post("/api/orders/checkout", headers=BUYER, json=dict(CHECKOUT, cart_item_ids=[a]))
    assert len(db.tables["cart_items"]) == 1 and db.tables["cart_items"][0]["variant_id"] == 3


def test_checkout_het_hang_thi_khong_tao_gi(client, db):
    a = add(client, 1, 3).get_json()["data"]["id"]
    db.tables["product_variants"][0]["stock"] = 1  # có người khác mua mất trước đó
    res = client.post("/api/orders/checkout", headers=BUYER, json=dict(CHECKOUT, cart_item_ids=[a]))
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "OUT_OF_STOCK"
    assert db.tables.get("orders", []) == [] and len(db.tables["cart_items"]) == 1


def test_checkout_san_pham_bi_go_khoi_ban(client, db):
    a = add(client, 1, 1).get_json()["data"]["id"]
    db.tables["products"][0]["moderation_status"] = "blocked"
    res = client.post("/api/orders/checkout", headers=BUYER, json=dict(CHECKOUT, cart_item_ids=[a]))
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "PRODUCT_UNAVAILABLE"


def test_checkout_gio_cua_nguoi_khac_hoac_khong_co(client):
    a = add(client, 1, 1).get_json()["data"]["id"]
    res = client.post("/api/orders/checkout", headers=OTHER, json=dict(CHECKOUT, cart_item_ids=[a]))
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "CART_CHANGED"


@pytest.mark.parametrize("patch", [
    {"cart_item_ids": []}, {"cart_item_ids": ["abc"]}, {"receiver_name": ""}, {"phone": "123"},
    {"address": ""}, {"payment_method": "bitcoin"}, {"lat": 999, "lng": 106.7},
])
def test_checkout_du_lieu_sai_tra_400(client, patch):
    a = add(client, 1, 1).get_json()["data"]["id"]
    body = dict(CHECKOUT, cart_item_ids=[a])
    body.update(patch)  # ghi đè đúng trường cần làm sai
    res = client.post("/api/orders/checkout", headers=BUYER, json=body)
    assert res.status_code == 400


# ---------- danh sách, chi tiết, hủy ----------

def place_order(client, variant_id=1, quantity=1):
    item_id = add(client, variant_id, quantity).get_json()["data"]["id"]
    return client.post("/api/orders/checkout", headers=BUYER, json=dict(CHECKOUT, cart_item_ids=[item_id])).get_json()["data"]["orders"][0]


def test_danh_sach_don_va_loc_trang_thai(client, db):
    first = place_order(client)
    place_order(client, 3)
    db.tables["orders"][0]["status"] = "completed"
    all_orders = client.get("/api/orders", headers=BUYER).get_json()["data"]["items"]
    assert len(all_orders) == 2
    assert [o["id"] for o in client.get("/api/orders?status=history", headers=BUYER).get_json()["data"]["items"]] == [first["id"]]
    assert len(client.get("/api/orders?status=pending", headers=BUYER).get_json()["data"]["items"]) == 1
    assert client.get("/api/orders?status=abc", headers=BUYER).status_code == 400
    assert client.get("/api/orders", headers=OTHER).get_json()["data"]["items"] == []  # không thấy đơn người khác


def test_chi_tiet_don_va_quyen_so_huu(client):
    order = place_order(client)
    detail = client.get(f"/api/orders/{order['id']}", headers=BUYER).get_json()["data"]
    assert detail["shop"]["name"] == "Shop A" and detail["items"][0]["product_name"] == "Áo thun basic"
    assert client.get(f"/api/orders/{order['id']}", headers=OTHER).status_code == 404


def test_huy_don_cho_xac_nhan(client, db):
    order = place_order(client)
    res = client.post(f"/api/orders/{order['id']}/cancel", headers=BUYER)
    assert res.status_code == 200 and res.get_json()["data"]["status"] == "cancelled"
    again = client.post(f"/api/orders/{order['id']}/cancel", headers=BUYER)
    assert again.status_code == 422  # đã hủy rồi


def test_khong_huy_duoc_don_dang_xu_ly_hoac_cua_nguoi_khac(client, db):
    order = place_order(client)
    assert client.post(f"/api/orders/{order['id']}/cancel", headers=OTHER).status_code == 404
    db.tables["orders"][0]["status"] = "processing"
    res = client.post(f"/api/orders/{order['id']}/cancel", headers=BUYER)
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "INVALID_STATE"


# ---------- sự kiện ----------

def test_ghi_su_kien_khach_va_nguoi_dung(client, db):
    assert client.post("/api/events", json={"shop_id": 1, "product_id": 1, "event_type": "view"}).status_code == 201
    assert client.post("/api/events", headers=BUYER, json={"shop_id": 1, "event_type": "add_to_cart"}).status_code == 201
    events = db.tables["analytics_events"]
    assert events[0]["user_id"] is None and events[1]["user_id"] == "u-buyer"


def test_su_kien_purchase_khong_cho_client_gui(client):
    assert client.post("/api/events", json={"shop_id": 1, "event_type": "purchase"}).status_code == 400
    assert client.post("/api/events", json={"event_type": "view"}).status_code == 400