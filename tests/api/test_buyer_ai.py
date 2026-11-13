"""Test API của Buyer: số đo, đánh giá sản phẩm, gợi ý sản phẩm, chatbot."""
import pytest

from api.index import create_app
from api.routes import ai as ai_routes
from api.routes import me as me_routes
from api.routes import products as products_routes
from api.services import auth as auth_service
from tests.api.fake_db import FakeDB

B1 = {"Authorization": "Bearer tok-b1"}
B2 = {"Authorization": "Bearer tok-b2"}
SELLER = {"Authorization": "Bearer tok-s1"}

BODY = {"height_cm": 170, "weight_kg": 60, "body_shape": "hourglass", "style_tags": ["Tối giản", "Công sở"],
        "budget_max": 300000, "wishes": "Thích đồ đi làm"}


def product(pid, shop, name, price, category="ao", tags=(), shapes=(), sold=0, status="approved", active=True):
    return {"id": pid, "shop_id": shop, "name": name, "description": f"Mô tả {name} đủ dài", "price": price, "category": category,
            "tags": list(tags), "suits_shapes": list(shapes), "sold_count": sold, "created_at": "2026-10-01",
            "moderation_status": status, "is_active": active}


@pytest.fixture
def db():
    return FakeDB(
        {
            "profiles": [
                {"id": "u-b1", "role": "buyer", "status": "active", "username": "buyer1", "full_name": "Nguyễn Thị Lan"},
                {"id": "u-b2", "role": "buyer", "status": "active", "username": "buyer2", "full_name": None},
                {"id": "u-s1", "role": "seller", "status": "active", "username": "seller1"},
            ],
            "shops": [
                {"id": 1, "owner_id": "u-s1", "name": "Shop A", "moderation_status": "approved"},
                {"id": 2, "owner_id": "u-s2", "name": "Shop B", "moderation_status": "approved"},
                {"id": 3, "owner_id": "u-s3", "name": "Shop C", "moderation_status": "blocked"},
            ],
            "products": [
                product(1, 1, "Áo sơ mi trắng", 250000, tags=["toi-gian", "cong-so"], shapes=["hourglass"], sold=10),
                product(2, 1, "Áo thun basic", 150000, tags=["basic"], shapes=["rectangle"], sold=5),
                product(3, 2, "Váy dài", 350000, "vay-dam", tags=["nu-tinh", "vintage"], shapes=["pear"], sold=2),
                product(4, 2, "Quần jeans", 380000, "quan", tags=["basic"], sold=7),
                product(5, 3, "Hàng của shop bị chặn", 100000, tags=["toi-gian"], sold=99),
                product(6, 2, "Hàng chờ duyệt", 100000, status="pending"),
                product(7, 2, "Hàng đã ẩn", 100000, active=False),
                product(8, 2, "Áo hết hàng", 100000, tags=["toi-gian"], sold=50),
            ],
            "product_variants": [
                {"id": 1, "product_id": 1, "size": "L", "color": "Trắng", "stock": 4},
                {"id": 2, "product_id": 2, "size": "S", "color": "Đen", "stock": 3},
                {"id": 3, "product_id": 3, "size": "M", "color": "Hồng", "stock": 0},
                {"id": 4, "product_id": 3, "size": "L", "color": "Hồng", "stock": 2},
                {"id": 5, "product_id": 4, "size": "XL", "color": "Xanh", "stock": 5},
                {"id": 6, "product_id": 8, "size": "L", "color": "Đen", "stock": 0},
                {"id": 7, "product_id": 5, "size": "L", "color": "Đen", "stock": 5},
            ],
            "product_images": [{"id": 1, "product_id": 1, "url": "https://img/a.jpg", "is_main": True, "position": 0}],
            "reviews": [
                {"id": 1, "product_id": 1, "user_id": "u-b1", "rating": 5, "comment": "Rất đẹp", "created_at": "2026-10-20"},
                {"id": 2, "product_id": 1, "user_id": "u-b2", "rating": 4, "comment": "Ổn", "created_at": "2026-10-21"},
            ],
            "body_profiles": [],
        },
        {"tok-b1": "u-b1", "tok-b2": "u-b2", "tok-s1": "u-s1"},
    )


@pytest.fixture
def client(db, monkeypatch):
    for module in (ai_routes, me_routes, products_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    return create_app().test_client()


def save_body(client, headers=B1, **kw):
    return client.put("/api/me/body-profile", json=dict(BODY, **kw), headers=headers)


# ---------- số đo ----------

def test_so_do_chua_co_thi_tra_ve_null(client):
    res = client.get("/api/me/body-profile", headers=B1)
    assert res.status_code == 200 and res.get_json()["data"] is None


def test_luu_so_do_tao_moi_roi_cap_nhat(client, db):
    first = save_body(client).get_json()["data"]
    assert first["height_cm"] == 170 and first["model_gender"] == "female"
    assert first["style_tags"] == ["toi-gian", "cong-so"] and first["user_id"] == "u-b1"
    second = save_body(client, height_cm=175, budget_max=None).get_json()["data"]
    assert second["height_cm"] == 175 and second["budget_max"] is None
    assert len(db.tables["body_profiles"]) == 1                      # cập nhật, không thêm dòng mới
    assert client.get("/api/me/body-profile", headers=B1).get_json()["data"]["height_cm"] == 175


def test_luu_duoc_kieu_nguoi_mau_nam(client):
    profile = save_body(client, model_gender="male").get_json()["data"]
    assert profile["model_gender"] == "male"


def test_so_do_cua_nguoi_nao_nguoi_do_thay(client):
    save_body(client)
    assert client.get("/api/me/body-profile", headers=B2).get_json()["data"] is None


@pytest.mark.parametrize("patch", [
    {"height_cm": 99}, {"height_cm": 231}, {"height_cm": "abc"}, {"height_cm": 170.5}, {"weight_kg": 24}, {"weight_kg": None},
    {"body_shape": "tron"}, {"body_shape": None}, {"model_gender": "other"},
    {"style_tags": "abc"}, {"style_tags": [str(i) for i in range(11)]},
    {"budget_max": -1}, {"wishes": "x" * 301},
])
def test_so_do_sai_tra_400(client, db, patch):
    res = save_body(client, **patch)
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "INVALID_INPUT"
    assert db.tables["body_profiles"] == []


def test_chi_buyer_moi_dung_duoc_so_do(client):
    assert client.get("/api/me/body-profile").status_code == 401
    assert client.get("/api/me/body-profile", headers=SELLER).status_code == 403
    assert save_body(client, headers=SELLER).status_code == 403


# ---------- đánh giá ----------

def test_xem_danh_gia_cong_khai_kem_diem_trung_binh(client):
    data = client.get("/api/products/1/reviews").get_json()["data"]
    assert data["rating_avg"] == 4.5 and data["rating_count"] == 2 and data["total"] == 2
    assert [r["id"] for r in data["items"]] == [2, 1]                                # mới nhất trước
    assert data["items"][0]["user_name"] == "buyer2" and data["items"][1]["user_name"] == "Nguyễn Thị Lan"
    assert set(data["items"][0]) == {"id", "rating", "comment", "created_at", "user_name"}


def test_danh_gia_san_pham_khong_hien_cong_khai_la_404(client):
    for pid in (5, 6, 7, 999):      # shop bị chặn, chờ duyệt, đã ẩn, không tồn tại
        assert client.get(f"/api/products/{pid}/reviews").status_code == 404


def test_gui_danh_gia_moi(client, db):
    res = client.post("/api/products/2/reviews", json={"rating": 5, "comment": "  Mặc rất thoải mái  "}, headers=B1)
    assert res.status_code == 201
    assert res.get_json()["data"]["comment"] == "Mặc rất thoải mái"
    assert client.get("/api/products/2/reviews").get_json()["data"]["rating_avg"] == 5.0


def test_gui_lai_thi_cap_nhat_khong_them_dong(client, db):
    res = client.post("/api/products/1/reviews", json={"rating": 3, "comment": "Đổi ý"}, headers=B1)   # buyer1 đã đánh giá 5 sao
    assert res.status_code == 200 and res.get_json()["data"]["rating"] == 3
    assert len([r for r in db.tables["reviews"] if r["product_id"] == 1]) == 2
    assert client.get("/api/products/1/reviews").get_json()["data"]["rating_avg"] == 3.5


@pytest.mark.parametrize("body", [{"rating": 0}, {"rating": 6}, {"rating": "5"}, {"rating": True}, {"rating": 4.5}, {}, {"rating": 5, "comment": "x" * 501}])
def test_danh_gia_sai_tra_400(client, db, body):
    assert client.post("/api/products/2/reviews", json=body, headers=B1).status_code == 400
    assert len(db.tables["reviews"]) == 2


def test_danh_gia_can_dang_nhap_buyer_va_san_pham_hop_le(client):
    assert client.post("/api/products/2/reviews", json={"rating": 5}).status_code == 401
    assert client.post("/api/products/2/reviews", json={"rating": 5}, headers=SELLER).status_code == 403
    assert client.post("/api/products/6/reviews", json={"rating": 5}, headers=B1).status_code == 404
    assert client.post("/api/products/5/reviews", json={"rating": 5}, headers=B1).status_code == 404


# ---------- gợi ý sản phẩm ----------

def recommend(client, headers=B1, **body):
    return client.post("/api/ai/recommend", json=body, headers=headers)


def test_chua_nhap_so_do_thi_422(client):
    res = recommend(client)
    assert res.status_code == 422 and res.get_json()["error"]["code"] == "NO_BODY_PROFILE"


def test_goi_y_chi_gom_san_pham_dang_ban_va_con_hang(client):
    save_body(client)
    items = recommend(client).get_json()["data"]["items"]
    ids = [i["product"]["id"] for i in items]
    assert set(ids) == {1, 2, 3, 4}          # loại: shop bị chặn (5), chờ duyệt (6), đã ẩn (7), hết hàng (8)


def test_goi_y_xep_theo_diem_va_co_ly_do(client):
    save_body(client)
    items = recommend(client).get_json()["data"]["items"]
    assert items[0]["product"]["id"] == 1                         # sơ mi: size L, hợp dáng, tag trùng, trong ngân sách, được đánh giá cao
    assert items[0]["score"] > items[1]["score"] >= items[-1]["score"]
    reasons = items[0]["reasons"]
    assert "Hợp size L theo số đo của bạn" in reasons and "Nằm trong ngân sách" in reasons and len(reasons) <= 3
    card = items[0]["product"]
    assert card["shop_name"] == "Shop A" and card["image_url"] == "https://img/a.jpg" and card["rating_avg"] == 4.5 and card["rating_count"] == 2


def test_goi_y_gioi_han_so_luong_va_moi_shop_toi_da_3(client, db):
    save_body(client)
    assert len(recommend(client, limit=2).get_json()["data"]["items"]) == 2
    for pid in range(20, 25):       # thêm 5 sản phẩm còn hàng cho shop A
        db.tables["products"].append(product(pid, 1, f"Áo mẫu {pid}", 200000, tags=["toi-gian"]))
        db.tables["product_variants"].append({"id": pid, "product_id": pid, "size": "L", "color": "Đen", "stock": 3})
    items = recommend(client, limit=20).get_json()["data"]["items"]
    assert len([i for i in items if i["product"]["shop_id"] == 1]) == 3


def test_mong_muon_them_doi_thu_tu(client):
    save_body(client, style_tags=[], wishes="")
    base = {i["product"]["id"]: i["score"] for i in recommend(client).get_json()["data"]["items"]}
    wished = {i["product"]["id"]: i for i in recommend(client, extra_wishes="mình muốn váy dài nữ tính").get_json()["data"]["items"]}
    assert wished[3]["score"] == pytest.approx(base[3] + 5) and wished[3]["reasons"][0] == "Đúng mong muốn của bạn"
    assert wished[1]["score"] == pytest.approx(base[1])


def test_goi_y_dung_so_do_cua_chinh_nguoi_dung(client):
    save_body(client, headers=B1)
    assert recommend(client, headers=B2).status_code == 422
    assert recommend(client, headers=SELLER).status_code == 403
    assert client.post("/api/ai/recommend", json={}).status_code == 401


def test_san_pham_het_hang_o_tat_ca_bien_the_khong_duoc_goi_y(client, db):
    save_body(client)
    db.tables["product_variants"][3]["stock"] = 0     # váy dài hết cả M lẫn L
    ids = [i["product"]["id"] for i in recommend(client).get_json()["data"]["items"]]
    assert 3 not in ids


# ---------- chatbot ----------

def chatbot(client, message, headers=None):
    return client.post("/api/ai/chatbot", json={"message": message}, headers=headers or {})


def test_chatbot_cong_khai_khong_can_dang_nhap(client):
    res = chatbot(client, "phí ship bao nhiêu")
    assert res.status_code == 200 and "chưa thu phí" in res.get_json()["data"]["reply"] and res.get_json()["data"]["products"] == []


def test_chatbot_kem_the_san_pham(client):
    data = chatbot(client, "tôi muốn mua áo sơ mi").get_json()["data"]
    assert data["reply"].startswith("Mình tìm thấy") and data["products"][0]["id"] == 1
    assert {"id", "name", "price", "image_url", "shop_name"} <= set(data["products"][0])


def test_chatbot_khong_goi_y_san_pham_bi_an(client):
    ids = [p["id"] for p in chatbot(client, "áo tối giản").get_json()["data"]["products"]]
    assert 5 not in ids and 6 not in ids and 7 not in ids          # shop bị chặn, chờ duyệt, đã ẩn
    assert len(ids) <= 4


def test_chatbot_kiem_tra_dau_vao(client):
    assert chatbot(client, "   ").status_code == 400
    assert chatbot(client, "x" * 301).status_code == 400
    assert client.post("/api/ai/chatbot", json={}).status_code == 400
    assert "Xin lỗi" in chatbot(client, "asdf qwer").get_json()["data"]["reply"]