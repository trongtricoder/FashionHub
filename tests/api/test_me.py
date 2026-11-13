"""Tests for persisted Buyer profile fields and avatar upload."""
from io import BytesIO

from api.index import create_app
from api.routes import me as me_routes
from api.services import auth as auth_service
from tests.api.fake_db import FakeDB


BUYER = {"Authorization": "Bearer buyer-token"}


def _client(monkeypatch, db):
    for module in (me_routes, auth_service):
        monkeypatch.setattr(module, "get_db", lambda: db)
    return create_app().test_client()


def test_buyer_can_load_and_update_profile(monkeypatch):
    db = FakeDB(
        {"profiles": [{
            "id": "buyer-1", "username": "buyer", "email": "buyer@example.test",
            "full_name": "Buyer", "phone": None, "address": None, "avatar_url": None,
            "role": "buyer", "status": "active",
        }]},
        {"buyer-token": "buyer-1"},
    )
    client = _client(monkeypatch, db)

    before = client.get("/api/me", headers=BUYER)
    assert before.status_code == 200
    assert before.get_json()["data"]["full_name"] == "Buyer"

    updated = client.patch("/api/me", headers=BUYER, json={
        "full_name": "Buyer One", "phone": "+84912345678", "address": "123 Đường Mẫu",
    })
    assert updated.status_code == 200
    assert updated.get_json()["data"]["phone"] == "+84912345678"
    assert db.tables["profiles"][0]["address"] == "123 Đường Mẫu"


def test_buyer_avatar_is_validated_uploaded_and_saved(monkeypatch):
    db = FakeDB(
        {"profiles": [{
            "id": "buyer-1", "username": "buyer", "email": "buyer@example.test",
            "role": "buyer", "status": "active",
        }]},
        {"buyer-token": "buyer-1"},
    )
    client = _client(monkeypatch, db)
    response = client.post(
        "/api/me/avatar",
        headers=BUYER,
        data={"file": (BytesIO(b"\x89PNG\r\n\x1a\nimage"), "avatar.png")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 200
    avatar_url = response.get_json()["data"]["avatar_url"]
    assert avatar_url.startswith("https://storage.test/avatars/buyer-1/")
    assert db.tables["profiles"][0]["avatar_url"] == avatar_url
    assert len(db.storage.files) == 1
    assert next(iter(db.storage.files))[0] == "avatars"


def test_buyer_avatar_rejects_non_image(monkeypatch):
    db = FakeDB(
        {"profiles": [{
            "id": "buyer-1", "username": "buyer", "email": "buyer@example.test",
            "role": "buyer", "status": "active",
        }]},
        {"buyer-token": "buyer-1"},
    )
    client = _client(monkeypatch, db)
    response = client.post(
        "/api/me/avatar",
        headers=BUYER,
        data={"file": (BytesIO(b"not an image"), "avatar.jpg")},
        content_type="multipart/form-data",
    )

    assert response.status_code == 400
    assert db.storage.files == {}
