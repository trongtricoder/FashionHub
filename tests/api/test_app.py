"""Test route bằng Flask test client với Supabase giả (không gọi mạng)."""
import pytest

from api.index import create_app
from api.routes import auth as auth_routes
from api.routes import products as products_routes
from api.services import auth as auth_service


class Result:
    def __init__(self, data):
        self.data = data


class FakeQuery:
    """Giả lập chuỗi table().select().eq()...execute() trên dữ liệu có sẵn."""
    def __init__(self, rows):
        self.rows, self.filters, self._limit = rows, [], None

    def select(self, *_): return self
    def eq(self, col, val): self.filters.append((col, val)); return self
    def limit(self, n): self._limit = n; return self

    def execute(self):
        rows = [r for r in self.rows if all(r.get(c) == v for c, v in self.filters)]
        return Result(rows[: self._limit] if self._limit else rows)


class FakeDB:
    def __init__(self, tables): self.tables = tables
    def table(self, name): return FakeQuery(self.tables.get(name, []))


PRODUCT = {
    "id": 1, "name": "Áo thun basic", "description": "Áo thun cotton mềm mịn dễ phối đồ mỗi ngày",
    "price": 150000, "category": "ao", "sold_count": 3, "created_at": "2026-10-01", "shop_id": 1,
    "moderation_status": "approved", "is_active": True, "shops": {"name": "Shop A"},
    "product_images": [{"url": "a.jpg", "is_main": True, "position": 0}],
    "product_variants": [{"size": "M", "stock": 4}], "reviews": [{"rating": 5}],
}


@pytest.fixture
def client(monkeypatch):
    db = FakeDB({
        "products": [PRODUCT, dict(PRODUCT, id=2, name="Bị chặn", moderation_status="blocked")],
        "profiles": [{"id": "u1", "username": "buyer1", "email": "buyer1@shop.example",
                      "role": "buyer", "status": "active"}],
    })
    for module in (products_routes, auth_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    return create_app().test_client()


def test_danh_sach_san_pham_chi_tra_approved(client):
    body = client.get("/api/products").get_json()
    assert body["ok"] is True
    assert [i["id"] for i in body["data"]["items"]] == [1]
    assert body["data"]["total"] == 1


def test_tham_so_sai_tra_400(client):
    res = client.get("/api/products?sort=abc")
    assert res.status_code == 400 and res.get_json()["error"]["code"] == "INVALID_INPUT"


def test_chi_tiet_khong_ton_tai_tra_404(client):
    res = client.get("/api/products/999")
    assert res.status_code == 404 and res.get_json()["ok"] is False


def test_route_api_khong_co_tra_json(client):
    res = client.get("/api/khong-co")
    assert res.status_code == 404 and res.get_json()["error"]["code"] == "NOT_FOUND"


def test_me_can_dang_nhap(client):
    res = client.get("/api/me")
    assert res.status_code == 401 and res.get_json()["error"]["code"] == "UNAUTHENTICATED"


def test_login_thieu_thong_tin(client):
    res = client.post("/api/auth/login", json={"identifier": "buyer1"})
    assert res.status_code == 400


def test_login_sai_tai_khoan_khong_lo_thong_tin(client):
    res = client.post("/api/auth/login", json={"identifier": "khong_ton_tai", "password": "x"})
    assert res.status_code == 401 and res.get_json()["error"]["code"] == "INVALID_CREDENTIALS"


def test_register_chan_vai_tro_admin(client):
    res = client.post("/api/auth/register", json={
        "username": "hacker", "email": "h@x.com", "password": "123456", "role": "admin"})
    assert res.status_code == 400


def test_register_username_trung(client):
    res = client.post("/api/auth/register", json={
        "username": "buyer1", "email": "new@x.com", "password": "123456", "role": "buyer"})
    assert res.status_code == 409 and res.get_json()["error"]["code"] == "USERNAME_TAKEN"


def test_san_pham_cua_shop_chua_duyet_khong_hien_cong_khai(client, monkeypatch):
    blocked_shop = dict(PRODUCT, id=3, name="Shop bị chặn", shops={"name": "Shop X", "moderation_status": "blocked"})
    db = FakeDB({"products": [PRODUCT, blocked_shop], "profiles": []})
    monkeypatch.setattr(products_routes, "get_db", lambda: db)
    ids = [i["id"] for i in client.get("/api/products").get_json()["data"]["items"]]
    assert ids == [1]                                    # sản phẩm 3 thuộc shop bị chặn nên ẩn
    assert client.get("/api/products/3").status_code == 404