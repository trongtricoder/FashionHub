"""Test Seller sửa shop, thêm sửa xóa sản phẩm (qua AI Detector), tải ảnh."""
import io

import pytest

from api.index import create_app
from api.routes import seller_catalog as catalog_routes
from api.services import auth as auth_service
from tests.api.fake_db import FakeDB

S1 = {"Authorization": "Bearer tok-s1"}
S2 = {"Authorization": "Bearer tok-s2"}
BUYER = {"Authorization": "Bearer tok-buyer"}
PNG = b"\x89PNG\r\n\x1a\n" + b"0" * 100


def good_body(**kw):
    body = {
        "name": "Áo sơ mi trắng", "description": "Áo sơ mi trắng công sở, chất vải thoáng mát, dễ giặt ủi.",
        "price": 250000, "category": "ao", "tags": ["Tối giản", "Công sở"], "suits_shapes": ["pear", "hourglass"],
        "variants": [{"size": "m", "color": "Trắng", "stock": 10}, {"size": "L", "color": "Trắng", "stock": 5}],
        "images": [{"url": "https://img/x.jpg", "is_main": False}, {"url": "https://img/y.jpg", "is_main": True}],
    }
    body.update(kw)
    return body


@pytest.fixture
def db():
    return FakeDB(
        {
            "profiles": [
                {"id": "u-s1", "role": "seller", "status": "active", "username": "seller1"},
                {"id": "u-s2", "role": "seller", "status": "active", "username": "seller2"},
                {"id": "u-buyer", "role": "buyer", "status": "active", "username": "buyer1"},
            ],
            "shops": [
                {"id": 1, "owner_id": "u-s1", "name": "Shop A", "description": "Cửa hàng thời trang chuyên các mẫu dễ mặc.",
                 "address": "12 Đường Mẫu", "lat": 10.76, "lng": 106.66, "prep_minutes": 30, "moderation_status": "approved"},
                {"id": 2, "owner_id": "u-s2", "name": "Shop B", "address": "B", "moderation_status": "approved"},
            ],
            "products": [
                {"id": 1, "shop_id": 1, "name": "Áo thun basic", "description": "Áo thun cotton mềm mịn dễ phối đồ", "price": 150000,
                 "category": "ao", "tags": [], "suits_shapes": [], "moderation_status": "approved", "sold_count": 3, "is_active": True},
                {"id": 2, "shop_id": 2, "name": "Váy dài", "description": "Váy dài thướt tha chất liệu mềm rủ", "price": 350000,
                 "category": "vay-dam", "tags": [], "suits_shapes": [], "moderation_status": "approved", "is_active": True},
            ],
            "product_variants": [
                {"id": 1, "product_id": 1, "size": "M", "color": "Trắng", "stock": 5},
                {"id": 2, "product_id": 1, "size": "L", "color": "Trắng", "stock": 10},
            ],
            "product_images": [{"id": 1, "product_id": 1, "url": "https://img/a.jpg", "is_main": True, "position": 0}],
            "order_items": [{"id": 1, "order_id": 1, "variant_id": 1, "product_id": 1, "product_name": "Áo thun basic", "quantity": 1, "price": 150000}],
            "moderation_queue": [], "ai_block_logs": [],
        },
        {"tok-s1": "u-s1", "tok-s2": "u-s2", "tok-buyer": "u-buyer"},
    )


@pytest.fixture
def client(db, monkeypatch):
    for module in (catalog_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    return create_app().test_client()


def create(client, headers=S1, **kw):
    return client.post("/api/seller/products", json=good_body(**kw), headers=headers)


def row(db, table, **where):
    return [r for r in db.tables[table] if all(r.get(k) == v for k, v in where.items())]


# ---------- quyền ----------

def test_chi_seller_moi_dung_duoc(client):
    assert client.post("/api/seller/products", json=good_body()).status_code == 401
    assert client.post("/api/seller/products", json=good_body(), headers=BUYER).status_code == 403
    assert client.put("/api/seller/shop", json={}, headers=BUYER).status_code == 403


# ---------- shop ----------

def test_sua_shop_hop_le(client, db):
    res = client.put("/api/seller/shop", headers=S1, json={
        "name": "Shop A mới", "description": "Cửa hàng thời trang chuyên các mẫu dễ mặc, giá tốt.",
        "address": "99 Đường Mới, Quận 1", "lat": 10.77, "lng": 106.7, "prep_minutes": 45})
    data = res.get_json()["data"]
    assert res.status_code == 200 and data["moderation"]["decision"] == "approved"
    assert row(db, "shops", id=1)[0]["name"] == "Shop A mới" and row(db, "shops", id=1)[0]["prep_minutes"] == 45


@pytest.mark.parametrize("patch", [{"name": ""}, {"lat": 10.7}, {"lat": 999, "lng": 106}, {"prep_minutes": 1}, {"prep_minutes": "abc"}])
def test_sua_shop_du_lieu_sai(client, patch):
    body = {"name": "Shop A", "description": "x" * 30, "address": "12 Đường Mẫu", "prep_minutes": 30}
    body.update(patch)
    assert client.put("/api/seller/shop", headers=S1, json=body).status_code == 400


def test_shop_dat_ten_cam_bi_chan_va_ghi_nhat_ky(client, db):
    res = client.put("/api/seller/shop", headers=S1, json={
        "name": "Shop hàng nhái fake", "description": "Bán hàng nhái, liên hệ zalo 0901234567 ngay hôm nay.", "address": "12 Đường Mẫu"})
    data = res.get_json()["data"]
    assert data["moderation"]["decision"] == "blocked" and data["moderation"]["account"]["action"] == "warning"
    assert row(db, "shops", id=1)[0]["moderation_status"] == "blocked"
    assert len(db.tables["moderation_queue"]) == 1 and db.tables["moderation_queue"][0]["target_type"] == "shop"
    assert {r["action"] for r in db.tables["ai_block_logs"]} == {"blocked", "warning"}


# ---------- thêm sản phẩm ----------

def test_them_san_pham_tot_duoc_dang_ngay(client, db):
    res = create(client)
    data = res.get_json()["data"]
    assert res.status_code == 201
    assert data["moderation"] == {"decision": "approved", "risk_score": 0, "reasons": [], "account": None}
    product = data["product"]
    assert product["moderation_status"] == "approved" and product["tags"] == ["toi-gian", "cong-so"]
    assert [(v["size"], v["stock"]) for v in product["variants"]] == [("M", 10), ("L", 5)]   # size được viết hoa
    assert [i["is_main"] for i in product["images"]] == [False, True]
    assert row(db, "products", id=product["id"])[0]["shop_id"] == 1
    assert db.tables["moderation_queue"] == [] and db.tables["ai_block_logs"] == []


def test_them_san_pham_nghi_ngo_vao_hang_doi(client, db):
    res = create(client, price=5000, images=[])    # giá bất thường 25 + không ảnh 20 = 45
    data = res.get_json()["data"]
    assert data["moderation"]["decision"] == "pending" and data["moderation"]["risk_score"] == 45
    assert data["moderation"]["account"] is None
    assert data["product"]["moderation_status"] == "pending"
    queue = db.tables["moderation_queue"]
    assert len(queue) == 1 and queue[0]["target_id"] == data["product"]["id"] and queue[0]["status"] == "pending"
    assert db.tables["ai_block_logs"][0]["action"] == "pending_review"


def test_them_san_pham_vi_pham_bi_chan(client, db):
    res = create(client, name="Áo Gucci replica", description="Hàng nhái cao cấp, liên hệ zalo 0901234567 để đặt hàng nhé.")
    data = res.get_json()["data"]
    assert data["moderation"]["decision"] == "blocked" and data["moderation"]["account"] == {"action": "warning", "blocked_count": 1}
    assert data["product"]["moderation_status"] == "blocked"
    assert [r["action"] for r in db.tables["ai_block_logs"]] == ["blocked", "warning"]
    assert len(db.tables["moderation_queue"]) == 1     # bị chặn vẫn vào hàng đợi để Admin xem lại


def test_ba_lan_bi_chan_thi_khoa_tai_khoan(client, db):
    bad = dict(name="Áo replica fake", description="Hàng nhái like auth, liên hệ zalo 0901234567 nhé các bạn.")
    results = [create(client, **bad).get_json()["data"]["moderation"]["account"] for _ in range(3)]
    assert [r["action"] for r in results] == ["warning", "warning", "ban"]
    assert row(db, "profiles", id="u-s1")[0]["status"] == "banned"
    assert create(client).status_code == 403    # tài khoản đã bị khóa, mọi API bị từ chối


def test_trung_ten_voi_shop_khac_bi_cong_diem(client):
    data = create(client, name="Váy dài", category="vay-dam").get_json()["data"]
    assert "duplicate" in [r["rule"] for r in data["moderation"]["reasons"]]


@pytest.mark.parametrize("patch", [
    {"name": ""}, {"name": "x" * 121}, {"category": "giay"}, {"price": -1}, {"price": "abc"}, {"price": 1.5},
    {"variants": []}, {"variants": [{"size": "M", "color": "Đen", "stock": -1}]},
    {"variants": [{"size": "M", "color": "Đen", "stock": 1}, {"size": "m", "color": "ĐEN", "stock": 2}]},
    {"images": [{"url": "https://i/%d.jpg" % i} for i in range(9)]}, {"images": [{"url": "ftp://x/y.jpg"}]},
    {"suits_shapes": ["tron"]}, {"tags": "abc"}, {"description": "x" * 2001},
])
def test_du_lieu_san_pham_sai_tra_400(client, db, patch):
    res = create(client, **patch)
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "INVALID_INPUT"
    assert len(db.tables["products"]) == 2    # không tạo thêm gì


# ---------- xem danh sách, chi tiết ----------

def test_danh_sach_chi_cua_shop_minh(client):
    create(client, price=5000, images=[])
    items = client.get("/api/seller/products", headers=S1).get_json()["data"]["items"]
    assert sorted(i["name"] for i in items) == ["Áo sơ mi trắng", "Áo thun basic"]
    basic = next(i for i in items if i["id"] == 1)
    assert basic["stock_total"] == 15 and basic["image_url"] == "https://img/a.jpg" and basic["sold_count"] == 3
    pending = client.get("/api/seller/products?status=pending", headers=S1).get_json()["data"]["items"]
    assert [i["name"] for i in pending] == ["Áo sơ mi trắng"] and pending[0]["risk_reasons"]
    assert client.get("/api/seller/products?status=abc", headers=S1).status_code == 400


def test_chi_tiet_va_quyen_so_huu(client):
    detail = client.get("/api/seller/products/1", headers=S1).get_json()["data"]
    assert detail["name"] == "Áo thun basic" and len(detail["variants"]) == 2 and len(detail["images"]) == 1
    assert client.get("/api/seller/products/2", headers=S1).status_code == 404    # sản phẩm của shop khác
    assert client.get("/api/seller/products/999", headers=S1).status_code == 404


# ---------- sửa sản phẩm ----------

def test_sua_san_pham_duoc_kiem_duyet_lai(client, db):
    pid = create(client).get_json()["data"]["product"]["id"]
    bad = client.put(f"/api/seller/products/{pid}", headers=S1, json=good_body(name="Áo replica fake"))
    assert bad.get_json()["data"]["moderation"]["decision"] == "blocked"
    assert row(db, "products", id=pid)[0]["moderation_status"] == "blocked"
    assert len(row(db, "moderation_queue", target_id=pid)) == 1

    fixed = client.put(f"/api/seller/products/{pid}", headers=S1, json=good_body())
    assert fixed.get_json()["data"]["moderation"]["decision"] == "approved"
    assert row(db, "products", id=pid)[0]["moderation_status"] == "approved"
    assert row(db, "moderation_queue", target_id=pid) == []     # mục chờ duyệt cũ đã dọn


def test_sua_san_pham_giu_id_bien_the_va_thay_anh(client, db):
    body = good_body(variants=[{"size": "M", "color": "Trắng", "stock": 99}, {"size": "XL", "color": "Đen", "stock": 4}],
                     images=[{"url": "https://img/new.jpg", "is_main": True}])
    # biến thể L/Trắng không còn: chưa có trong đơn hàng nào nên được xóa; M/Trắng (id 1) đã có trong đơn nên phải giữ
    res = client.put("/api/seller/products/1", headers=S1, json=body)
    assert res.status_code == 200
    variants = {(v["size"], v["color"]): v for v in db.tables["product_variants"] if v["product_id"] == 1}
    assert set(variants) == {("M", "Trắng"), ("XL", "Đen")}
    assert variants[("M", "Trắng")]["id"] == 1 and variants[("M", "Trắng")]["stock"] == 99   # giữ nguyên id
    assert [i["url"] for i in db.tables["product_images"] if i["product_id"] == 1] == ["https://img/new.jpg"]


def test_khong_xoa_duoc_bien_the_da_co_trong_don_hang(client, db):
    body = good_body(variants=[{"size": "L", "color": "Trắng", "stock": 3}])   # bỏ M/Trắng đã có trong đơn
    res = client.put("/api/seller/products/1", headers=S1, json=body)
    assert res.status_code == 400 and "M / Trắng" in res.get_json()["error"]["message"]
    assert {v["id"] for v in db.tables["product_variants"]} == {1, 2}       # không đổi gì
    assert row(db, "products", id=1)[0]["name"] == "Áo thun basic"


def test_khong_sua_duoc_san_pham_cua_shop_khac(client):
    assert client.put("/api/seller/products/2", headers=S1, json=good_body()).status_code == 404
    assert client.put("/api/seller/products/1", headers=S2, json=good_body()).status_code == 404


# ---------- xóa ----------

def test_xoa_san_pham_chua_co_don_thi_xoa_han(client, db):
    pid = create(client, price=5000, images=[]).get_json()["data"]["product"]["id"]      # đang chờ duyệt, có mục trong hàng đợi
    res = client.delete(f"/api/seller/products/{pid}", headers=S1)
    assert res.status_code == 200 and res.get_json()["data"] == {"hidden": False}
    assert row(db, "products", id=pid) == [] and row(db, "moderation_queue", target_id=pid) == []


def test_xoa_san_pham_da_co_don_thi_chi_an(client, db):
    res = client.delete("/api/seller/products/1", headers=S1)
    assert res.get_json()["data"] == {"hidden": True}
    assert row(db, "products", id=1)[0]["is_active"] is False
    assert client.get("/api/seller/products", headers=S1).get_json()["data"]["items"] == []
    assert client.delete("/api/seller/products/2", headers=S1).status_code == 404


# ---------- tải ảnh ----------

def upload(client, data, name="a.png", headers=S1):
    return client.post("/api/seller/uploads", headers=headers, content_type="multipart/form-data",
                       data={"file": (io.BytesIO(data), name)})


def test_tai_anh_thanh_cong(client, db):
    res = upload(client, PNG)
    url = res.get_json()["data"]["url"]
    assert res.status_code == 201 and url.startswith("https://storage.test/product-images/1/") and url.endswith(".png")
    data, options = next(iter(db.storage.files.values()))
    assert data == PNG and options == {"content-type": "image/png"}


def test_tai_anh_khong_tin_duoi_file(client):
    assert upload(client, b"day khong phai anh", name="virus.png").status_code == 400
    assert upload(client, b"<script>alert(1)</script>", name="a.jpg").status_code == 400
    assert upload(client, b"\xff\xd8\xff\xe0" + b"0" * 50, name="khongduoi").status_code == 201   # JPG thật dù tên lạ


def test_tai_anh_qua_lon_va_thieu_file(client):
    assert upload(client, PNG + b"0" * (5 * 1024 * 1024)).get_json()["error"]["code"] == "FILE_TOO_LARGE"
    assert upload(client, PNG + b"0" * (7 * 1024 * 1024)).status_code == 413      # vượt giới hạn của cả request
    assert client.post("/api/seller/uploads", headers=S1).status_code == 400
    assert upload(client, PNG, headers=BUYER).status_code == 403