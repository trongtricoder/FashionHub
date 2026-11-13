"""Tests for Buyer-Seller chat and support tickets."""
from api.index import create_app
from api.routes import auth as auth_routes
from api.routes import chat as chat_routes
from api.routes import tickets as tickets_routes
from api.services import auth as auth_service
from tests.api.fake_db import FakeDB


PROFILES = [
    {"id": "buyer-1", "username": "buyer", "full_name": "Buyer One", "role": "buyer", "status": "active"},
    {"id": "buyer-2", "username": "other", "role": "buyer", "status": "active"},
    {"id": "seller-1", "username": "seller", "full_name": "Seller One", "role": "seller", "status": "active"},
    {"id": "seller-2", "username": "seller2", "role": "seller", "status": "active"},
    {"id": "admin-1", "username": "admin", "role": "admin", "status": "active"},
]


def _client(monkeypatch, db):
    for module in (auth_routes, auth_service, chat_routes, tickets_routes):
        monkeypatch.setattr(module, "get_db", lambda: db)
    app = create_app()
    return app.test_client()


def _headers(token):
    return {"Authorization": f"Bearer {token}"}


def test_chat_send_poll_unread_and_mark_read(monkeypatch):
    db = FakeDB(
        {"profiles": PROFILES, "shops": [{"id": 7, "owner_id": "seller-1", "name": "Shop One"}]},
        {"buyer-token": "buyer-1", "seller-token": "seller-1"},
    )
    client = _client(monkeypatch, db)

    sent = client.post("/api/chat/messages", headers=_headers("buyer-token"),
                       json={"shop_id": 7, "content": "Shop còn size M không?"})
    assert sent.status_code == 201
    assert sent.get_json()["data"]["receiver_id"] == "seller-1"

    inbox = client.get("/api/chat/conversations", headers=_headers("seller-token")).get_json()["data"]
    assert inbox[0]["unread"] == 1
    assert inbox[0]["name"] == "Buyer One"

    thread = client.get("/api/chat/messages?with=buyer-1", headers=_headers("seller-token"))
    assert [item["content"] for item in thread.get_json()["data"]] == ["Shop còn size M không?"]
    assert db.tables["messages"][0]["is_read"] is True


def test_buyer_message_carries_product_context_to_seller(monkeypatch):
    db = FakeDB(
        {
            "profiles": PROFILES,
            "shops": [{"id": 7, "owner_id": "seller-1", "name": "Shop One"}],
            "products": [{"id": 15, "name": "Áo linen", "price": 250000, "shop_id": 7}],
            "product_images": [{"product_id": 15, "url": "https://img.test/linen.png", "is_main": True, "position": 0}],
        },
        {"buyer-token": "buyer-1", "seller-token": "seller-1"},
    )
    client = _client(monkeypatch, db)

    sent = client.post("/api/chat/messages", headers=_headers("buyer-token"), json={
        "shop_id": 7, "product_id": 15, "content": "Mẫu này còn màu be không?",
    })
    assert sent.status_code == 201
    assert sent.get_json()["data"]["product"]["name"] == "Áo linen"

    inbox = client.get("/api/chat/conversations", headers=_headers("seller-token")).get_json()["data"]
    assert inbox[0]["last_product"]["id"] == 15
    thread = client.get("/api/chat/messages?with=buyer-1", headers=_headers("seller-token"))
    assert thread.get_json()["data"][0]["product"]["image_url"] == "https://img.test/linen.png"


def test_chat_rejects_product_from_another_shop(monkeypatch):
    db = FakeDB(
        {
            "profiles": PROFILES,
            "shops": [{"id": 7, "owner_id": "seller-1", "name": "Shop One"}],
            "products": [{"id": 15, "name": "Áo linen", "price": 250000, "shop_id": 8}],
        },
        {"buyer-token": "buyer-1"},
    )
    client = _client(monkeypatch, db)
    response = client.post("/api/chat/messages", headers=_headers("buyer-token"), json={
        "shop_id": 7, "product_id": 15, "content": "Còn hàng không?",
    })
    assert response.status_code == 400
    assert db.tables.get("messages", []) == []


def test_seller_cannot_start_conversation_with_unrelated_buyer(monkeypatch):
    db = FakeDB(
        {
            "profiles": PROFILES,
            "shops": [{"id": 7, "owner_id": "seller-1", "name": "Shop One"}],
            "orders": [],
        },
        {"seller-token": "seller-1"},
    )
    client = _client(monkeypatch, db)
    response = client.post("/api/chat/messages", headers=_headers("seller-token"),
                           json={"receiver_id": "buyer-2", "content": "Xin chào"})
    assert response.status_code == 404


def test_ticket_owner_and_admin_can_read_and_reply(monkeypatch):
    db = FakeDB(
        {"profiles": PROFILES},
        {"buyer-token": "buyer-1", "other-token": "buyer-2", "admin-token": "admin-1"},
    )
    client = _client(monkeypatch, db)

    created = client.post("/api/tickets", headers=_headers("buyer-token"),
                          json={"subject": "Hỏi đơn hàng", "content": "Đơn của tôi đang ở đâu?"})
    assert created.status_code == 201
    ticket_id = created.get_json()["data"]["id"]

    other_tickets = client.get("/api/tickets", headers=_headers("other-token")).get_json()["data"]["items"]
    assert other_tickets == []

    reply = client.post(f"/api/tickets/{ticket_id}/reply", headers=_headers("admin-token"),
                        json={"content": "Chúng tôi đang kiểm tra."})
    assert reply.status_code == 201
    admin_tickets = client.get("/api/tickets", headers=_headers("admin-token")).get_json()["data"]["items"]
    assert admin_tickets[0]["replies"][0]["content"] == "Chúng tôi đang kiểm tra."


def test_user_cannot_reply_to_another_users_ticket(monkeypatch):
    db = FakeDB(
        {
            "profiles": PROFILES,
            "tickets": [{"id": 1, "user_id": "buyer-1", "parent_id": None, "subject": "Support",
                         "content": "Help", "status": "open", "created_at": "2026-01-01T00:00:00+00:00"}],
        },
        {"other-token": "buyer-2"},
    )
    client = _client(monkeypatch, db)
    response = client.post("/api/tickets/1/reply", headers=_headers("other-token"), json={"content": "Reply"})
    assert response.status_code == 404
