"""Test Admin: tài khoản, hàng đợi duyệt, nhật ký AI chặn, đổi mật khẩu."""
from datetime import datetime, timedelta, timezone

import pytest

from api.index import create_app
from api.routes import admin as admin_routes
from api.routes import me as me_routes
from api.routes import seller as seller_routes
from api.services import auth as auth_service
from api.services import passwords
from tests.api.fake_db import FakeDB

ADMIN = {"Authorization": "Bearer tok-admin"}
BUYER = {"Authorization": "Bearer tok-b2"}
SELLER = {"Authorization": "Bearer tok-s2"}

UID = {  # id hợp lệ dạng UUID cho từng tài khoản
    "admin": "00000000-0000-4000-8000-000000000001",
    "admin2": "00000000-0000-4000-8000-000000000002",
    "b1": "00000000-0000-4000-8000-000000000011",
    "b2": "00000000-0000-4000-8000-000000000012",
    "s1": "00000000-0000-4000-8000-000000000101",
    "s2": "00000000-0000-4000-8000-000000000102",
}


def now(minutes_ago=0):
    return (datetime.now(timezone.utc) - timedelta(minutes=minutes_ago)).isoformat()


@pytest.fixture
def db():
    return FakeDB(
        {
            "profiles": [
                {"id": UID["admin"], "username": "admin", "email": "admin@shop.example", "full_name": "Quản trị viên", "role": "admin", "status": "active", "created_at": "2026-10-01"},
                {"id": UID["admin2"], "username": "admin2", "email": "admin2@shop.example", "role": "admin", "status": "active", "created_at": "2026-10-02"},
                {"id": UID["b1"], "username": "buyer1", "email": "buyer1@shop.example", "full_name": "Nguyễn Thị Lan", "role": "buyer", "status": "active", "created_at": "2026-10-03", "must_change_password": False},
                {"id": UID["b2"], "username": "buyer2", "email": "buyer2@shop.example", "full_name": "Trần Minh Khoa", "role": "buyer", "status": "banned", "created_at": "2026-10-04", "must_change_password": True},
                {"id": UID["s1"], "username": "seller1", "email": "seller1@shop.example", "full_name": "Chủ shop 1", "role": "seller", "status": "active", "created_at": "2026-10-05"},
                {"id": UID["s2"], "username": "seller2", "email": "seller2@shop.example", "full_name": "Chủ shop 2", "role": "seller", "status": "active", "created_at": "2026-10-06"},
            ],
            "shops": [
                {"id": 1, "owner_id": UID["s1"], "name": "Shop A", "description": "Mô tả shop A", "address": "12 Đường Mẫu", "moderation_status": "approved"},
                {"id": 2, "owner_id": UID["s2"], "name": "Shop B", "description": "", "address": "", "moderation_status": "pending"},
            ],
            "products": [
                {"id": 1, "shop_id": 1, "name": "Áo thun basic", "description": "Áo thun cotton mềm mịn", "price": 150000, "category": "ao", "tags": ["basic"],
                 "moderation_status": "approved", "risk_score": 0, "risk_reasons": [], "is_active": True},
                {"id": 2, "shop_id": 1, "name": "Áo Gucci replica", "description": "Hàng nhái, zalo 0901234567", "price": 99000, "category": "ao", "tags": [],
                 "moderation_status": "blocked", "risk_score": 95, "risk_reasons": [{"rule": "banned_keyword", "points": 70, "detail": "Chứa từ khóa cấm: replica"}], "is_active": True},
                {"id": 3, "shop_id": 1, "name": "Hàng giá rẻ", "description": "x", "price": 5000, "category": "ao", "tags": [],
                 "moderation_status": "pending", "risk_score": 45, "risk_reasons": [{"rule": "price_anomaly", "points": 25, "detail": "Giá thấp bất thường"}], "is_active": True},
            ],
            "product_images": [{"id": 1, "product_id": 2, "url": "https://img/g.jpg", "is_main": True, "position": 0}],
            "orders": [{"id": 1, "buyer_id": UID["b1"], "shop_id": 1, "total": 1, "status": "completed"}],
            "moderation_queue": [
                {"id": 1, "target_type": "product", "target_id": 2, "risk_score": 95, "status": "pending", "created_at": now(30),
                 "reasons": [{"rule": "banned_keyword", "points": 70, "detail": "Chứa từ khóa cấm: replica"}]},
                {"id": 2, "target_type": "product", "target_id": 3, "risk_score": 45, "status": "pending", "created_at": now(20),
                 "reasons": [{"rule": "price_anomaly", "points": 25, "detail": "Giá thấp bất thường"}]},
                {"id": 3, "target_type": "shop", "target_id": 2, "risk_score": 20, "status": "pending", "created_at": now(10), "reasons": []},
                {"id": 4, "target_type": "product", "target_id": 1, "risk_score": 40, "status": "approved", "created_at": now(500), "reasons": []},
            ],
            "ai_block_logs": [
                {"id": 1, "target_type": "product", "target_id": "2", "owner_id": UID["s1"], "risk_score": 95, "reasons": [{"detail": "Chứa từ khóa cấm: replica"}], "action": "blocked", "restored": False, "created_at": now(30)},
                {"id": 2, "target_type": "product", "target_id": "3", "owner_id": UID["s1"], "risk_score": 45, "reasons": [], "action": "pending_review", "restored": False, "created_at": now(20)},
                {"id": 3, "target_type": "account", "target_id": UID["s1"], "owner_id": UID["s1"], "reasons": [], "action": "ban", "restored": False, "created_at": now(15)},
                {"id": 4, "target_type": "shop", "target_id": "2", "owner_id": UID["s2"], "risk_score": 20, "reasons": [], "action": "pending_review", "restored": True, "created_at": now(10)},
                {"id": 5, "target_type": "product", "target_id": "1", "owner_id": UID["s1"], "risk_score": 40, "reasons": [], "action": "blocked", "restored": False,
                 "created_at": (datetime.now(timezone.utc) - timedelta(days=3)).isoformat()},
            ],
        },
        {"tok-admin": UID["admin"], "tok-b2": UID["b2"], "tok-s2": UID["s2"]},
    )


@pytest.fixture
def client(db, monkeypatch):
    for module in (admin_routes, me_routes, seller_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    return create_app().test_client()


def get(client, url, headers=ADMIN):
    return client.get(url, headers=headers)


def post(client, url, body=None, headers=ADMIN):
    return client.post(url, json=body or {}, headers=headers)


def profile(db, key):
    return next(p for p in db.tables["profiles"] if p["id"] == UID[key])


# ---------- quyền ----------

def test_chi_admin_moi_vao_duoc(client):
    assert client.get("/api/admin/users").status_code == 401
    assert get(client, "/api/admin/users", BUYER).status_code in (403,)       # buyer2 đang bị khóa nên 403 ACCOUNT_BANNED
    assert get(client, "/api/admin/moderation", SELLER).status_code == 403
    assert post(client, "/api/admin/moderation/1/approve", headers=SELLER).status_code == 403


# ---------- tài khoản ----------

def test_danh_sach_tai_khoan_khong_lo_mat_khau(client):
    data = get(client, "/api/admin/users").get_json()["data"]
    assert data["total"] == 6
    for item in data["items"]:
        assert set(item) == {"id", "username", "email", "role", "status", "created_at"}


def test_loc_tai_khoan(client):
    ids = lambda q: sorted(i["username"] for i in get(client, f"/api/admin/users{q}").get_json()["data"]["items"])
    assert ids("?role=seller") == ["seller1", "seller2"]
    assert ids("?status=banned") == ["buyer2"]
    assert ids("?q=LAN") == ["buyer1"]                       # tìm theo họ tên, không phân biệt hoa thường
    assert ids("?q=tran minh") == ["buyer2"]                 # bỏ dấu vẫn tìm được
    assert ids("?q=seller1@shop") == ["seller1"]
    assert get(client, "/api/admin/users?role=hacker").status_code == 400
    assert get(client, "/api/admin/users?status=abc").status_code == 400


def test_phan_trang_tai_khoan(client):
    data = get(client, "/api/admin/users?page=2&page_size=4").get_json()["data"]
    assert data["page"] == 2 and data["total"] == 6 and len(data["items"]) == 2


def test_dat_lai_mat_khau(client, db):
    res = post(client, f"/api/admin/users/{UID['b1']}/reset-password")
    temp = res.get_json()["data"]["temp_password"]
    assert res.status_code == 200 and len(temp) == 10 and temp.isalnum()
    assert db.passwords[UID["b1"]] == temp
    assert profile(db, "b1")["must_change_password"] is True


def test_khong_thao_tac_tren_admin_hoac_tai_khoan_la(client, db):
    assert post(client, f"/api/admin/users/{UID['admin2']}/reset-password").status_code == 403
    assert post(client, f"/api/admin/users/{UID['admin']}/status", {"status": "banned"}).status_code == 403
    assert client.delete(f"/api/admin/users/{UID['admin2']}", headers=ADMIN).status_code == 403
    assert post(client, "/api/admin/users/khong-phai-uuid/reset-password").status_code == 404
    assert post(client, "/api/admin/users/00000000-0000-4000-8000-0000000009ff/status", {"status": "banned"}).status_code == 404
    assert profile(db, "admin2")["status"] == "active"


def test_dat_lai_mat_khau_loi_tu_supabase(client, db):
    db.tables["profiles"].append({"id": "u-fail", "username": "x", "email": "x@x.com", "role": "buyer", "status": "active"})
    res = client.post("/api/admin/users/00000000-0000-4000-8000-0000000000aa/reset-password", headers=ADMIN)
    assert res.status_code == 404
    db.tables["profiles"][-1]["id"] = "00000000-0000-4000-8000-0000000000aa"
    # Supabase giả chỉ lỗi với id "u-fail", id UUID thì thành công: kiểm tra đường lỗi bằng cách ép hàm báo lỗi
    db.auth.admin.update_user_by_id = lambda uid, attrs: (_ for _ in ()).throw(RuntimeError("lỗi"))
    res = client.post("/api/admin/users/00000000-0000-4000-8000-0000000000aa/reset-password", headers=ADMIN)
    assert res.status_code == 502 and res.get_json()["error"]["code"] == "RESET_FAILED"


def test_khoa_va_mo_khoa(client, db):
    res = post(client, f"/api/admin/users/{UID['b1']}/status", {"status": "banned", "reason": "spam"})
    assert res.get_json()["data"]["status"] == "banned" and profile(db, "b1")["status"] == "banned"
    assert post(client, f"/api/admin/users/{UID['b1']}/status", {"status": "active"}).get_json()["data"]["status"] == "active"
    assert post(client, f"/api/admin/users/{UID['b1']}/status", {"status": "xoa"}).status_code == 400


def test_xoa_tai_khoan_da_co_don_hang_bi_chan(client, db):
    res = client.delete(f"/api/admin/users/{UID['b1']}", headers=ADMIN)             # buyer có đơn
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "HAS_ORDERS"
    assert client.delete(f"/api/admin/users/{UID['s1']}", headers=ADMIN).status_code == 409   # shop có đơn
    assert db.deleted_users == []


def test_xoa_tai_khoan_chua_co_don(client, db):
    assert client.delete(f"/api/admin/users/{UID['s2']}", headers=ADMIN).status_code == 200
    assert db.deleted_users == [UID["s2"]] and all(p["id"] != UID["s2"] for p in db.tables["profiles"])


# ---------- hàng đợi duyệt ----------

def test_danh_sach_cho_duyet_mac_dinh(client):
    items = get(client, "/api/admin/moderation").get_json()["data"]["items"]
    assert [i["id"] for i in items] == [3, 2, 1]                   # mới nhất trước, bỏ mục đã duyệt
    first = next(i for i in items if i["id"] == 1)
    assert first["name"] == "Áo Gucci replica" and first["owner_name"] == "Chủ shop 1" and first["risk_score"] == 95
    shop_item = next(i for i in items if i["id"] == 3)
    assert shop_item["target_type"] == "shop" and shop_item["name"] == "Shop B" and shop_item["owner_name"] == "Chủ shop 2"
    done = get(client, "/api/admin/moderation?status=approved").get_json()["data"]["items"]
    assert [i["id"] for i in done] == [4]
    assert get(client, "/api/admin/moderation?status=abc").status_code == 400


def test_chi_tiet_muc_kiem_duyet(client):
    detail = get(client, "/api/admin/moderation/1").get_json()["data"]
    assert detail["description"] == "Hàng nhái, zalo 0901234567" and detail["price"] == 99000
    assert detail["images"] == [{"url": "https://img/g.jpg", "is_main": True}] and detail["shop_name"] == "Shop A"
    assert detail["reasons"][0]["detail"].startswith("Chứa từ khóa cấm")
    shop = get(client, "/api/admin/moderation/3").get_json()["data"]
    assert shop["address"] == "" and shop["current_status"] == "pending"
    assert get(client, "/api/admin/moderation/999").status_code == 404


def test_duyet_muc_cho(client, db):
    assert post(client, "/api/admin/moderation/2/approve").status_code == 200
    assert next(p for p in db.tables["products"] if p["id"] == 3)["moderation_status"] == "approved"
    item = next(q for q in db.tables["moderation_queue"] if q["id"] == 2)
    assert item["status"] == "approved" and item["reviewed_by"] == UID["admin"] and item["reviewed_at"]
    assert next(l for l in db.tables["ai_block_logs"] if l["id"] == 2)["restored"] is True
    assert post(client, "/api/admin/moderation/2/approve").status_code == 422      # đã xử lý rồi
    assert post(client, "/api/admin/moderation/999/approve").status_code == 404


def test_tu_choi_bat_buoc_co_ly_do(client, db):
    assert post(client, "/api/admin/moderation/1/reject", {"reason": "  "}).status_code == 400
    assert post(client, "/api/admin/moderation/1/reject", {"reason": "x" * 301}).status_code == 400
    assert next(p for p in db.tables["products"] if p["id"] == 2)["moderation_status"] == "blocked"


def test_tu_choi_san_pham_ly_do_hien_cho_seller(client, db):
    res = post(client, "/api/admin/moderation/2/reject", {"reason": "Giá quá thấp, nghi ngờ lừa đảo"})
    assert res.status_code == 200
    product = next(p for p in db.tables["products"] if p["id"] == 3)
    assert product["moderation_status"] == "rejected"
    assert product["risk_reasons"][0] == {"rule": "admin_rejected", "points": 0, "detail": "Admin từ chối: Giá quá thấp, nghi ngờ lừa đảo"}
    assert product["risk_reasons"][1]["rule"] == "price_anomaly"                      # lý do cũ vẫn giữ
    item = next(q for q in db.tables["moderation_queue"] if q["id"] == 2)
    assert item["status"] == "rejected" and item["reject_reason"] == "Giá quá thấp, nghi ngờ lừa đảo"


def test_tu_choi_shop_seller_doc_duoc_ly_do(client, db):
    assert post(client, "/api/admin/moderation/3/reject", {"reason": "Thiếu địa chỉ cửa hàng"}).status_code == 200
    shop = client.get("/api/seller/shop", headers=SELLER).get_json()["data"]
    assert shop["moderation_status"] == "rejected" and shop["reject_reason"] == "Thiếu địa chỉ cửa hàng"


# ---------- AI chặn hôm nay ----------

def test_ai_chan_hom_nay(client):
    data = get(client, "/api/admin/ai-blocked").get_json()["data"]
    assert data["counts"] == {"blocked_today": 1, "pending": 3, "restored": 1}
    assert [i["id"] for i in data["items"]] == [4, 3, 2, 1]                           # log 5 của 3 ngày trước không vào
    by_id = {i["id"]: i for i in data["items"]}
    assert by_id[1]["target_name"] == "Áo Gucci replica" and by_id[1]["owner_name"] == "Chủ shop 1" and by_id[1]["action"] == "blocked"
    assert by_id[3]["target_type"] == "account" and by_id[3]["target_name"] == "seller1" and by_id[3]["action"] == "ban"
    assert by_id[4]["target_name"] == "Shop B" and by_id[4]["restored"] is True


def test_ai_chan_theo_ngay_khac(client):
    day = (datetime.now(timezone.utc) - timedelta(days=3)).astimezone(timezone(timedelta(hours=7))).date().isoformat()
    data = get(client, f"/api/admin/ai-blocked?date={day}").get_json()["data"]
    assert [i["id"] for i in data["items"]] == [5] and data["counts"]["blocked_today"] == 1
    assert get(client, "/api/admin/ai-blocked?date=hom-qua").status_code == 400


def test_khoi_phuc_san_pham_bi_chan_nham(client, db):
    assert post(client, "/api/admin/ai-blocked/1/restore").status_code == 200
    assert next(p for p in db.tables["products"] if p["id"] == 2)["moderation_status"] == "approved"
    assert next(q for q in db.tables["moderation_queue"] if q["id"] == 1)["status"] == "approved"
    assert next(l for l in db.tables["ai_block_logs"] if l["id"] == 1)["restored"] is True
    assert post(client, "/api/admin/ai-blocked/1/restore").status_code == 422


def test_khoi_phuc_mo_khoa_tai_khoan(client, db):
    db.tables["profiles"][4]["status"] = "banned"        # seller1 bị khóa bởi Detector
    assert post(client, "/api/admin/ai-blocked/3/restore").status_code == 200
    assert profile(db, "s1")["status"] == "active"
    assert post(client, "/api/admin/ai-blocked/999/restore").status_code == 404


def test_khoi_phuc_shop(client, db):
    db.tables["ai_block_logs"][3]["restored"] = False
    assert post(client, "/api/admin/ai-blocked/4/restore").status_code == 200
    assert next(s for s in db.tables["shops"] if s["id"] == 2)["moderation_status"] == "approved"


# ---------- đổi mật khẩu (sau khi Admin đặt lại) ----------

def test_doi_mat_khau_bo_co_bat_doi(client, db):
    db.tables["profiles"][3]["status"] = "active"          # buyer2 được mở khóa
    h = {"Authorization": "Bearer tok-b2"}
    assert client.post("/api/me/change-password", json={"new_password": "12345"}, headers=h).status_code == 400
    assert client.post("/api/me/change-password", json={"new_password": "MatKhauMoi9"}, headers=h).status_code == 200
    assert db.passwords[UID["b2"]] == "MatKhauMoi9" and profile(db, "b2")["must_change_password"] is False
    assert client.post("/api/me/change-password", json={"new_password": "MatKhauMoi9"}).status_code == 401


def test_mat_khau_tam_ngau_nhien_va_du_manh():
    seen = {passwords.generate_temp_password() for _ in range(50)}
    assert len(seen) == 50
    for p in seen:
        assert len(p) == 10 and p.isalnum() and any(c.isdigit() for c in p) and any(c.isalpha() for c in p)