"""Tin nhắn Buyer-Seller và danh sách hội thoại."""
from datetime import datetime, timezone

from flask import Blueprint, g, request

from ..services import catalog
from ..services.auth import require_role
from ..services.db import get_db
from ..services.responses import fail, ok

bp = Blueprint("chat", __name__, url_prefix="/api/chat")
MAX_MESSAGES = 500
MAX_CONTENT_LENGTH = 2000


def _profile(db, user_id):
    rows = db.table("profiles").select("id,username,full_name,avatar_url,role,status").eq(
        "id", user_id).limit(1).execute().data
    return rows[0] if rows else None


def _profiles(db, user_ids):
    if not user_ids:
        return {}
    rows = db.table("profiles").select("id,username,full_name,avatar_url,role,status").in_(
        "id", list(user_ids)).limit(MAX_MESSAGES).execute().data
    return {row["id"]: row for row in rows}


def _shop(db, shop_id):
    rows = db.table("shops").select("id,owner_id,name,moderation_status").eq(
        "id", shop_id).limit(1).execute().data
    return rows[0] if rows else None


def _may_chat(db, partner):
    user = g.user
    if (user["role"] not in ("buyer", "seller") or partner["id"] == user["id"]
            or partner.get("status") != "active"):
        return False
    if user["role"] == "buyer":
        if partner["role"] != "seller":
            return False
        shops = (db.table("shops").select("id,moderation_status").eq("owner_id", partner["id"])
                 .limit(1).execute().data)
        return bool(shops and shops[0].get("moderation_status", "approved") == "approved")

    if partner["role"] != "buyer":
        return False
    shops = db.table("shops").select("id").eq("owner_id", user["id"]).limit(1).execute().data
    if not shops:
        return False
    existing = (db.table("messages").select("id").eq("sender_id", partner["id"])
                .eq("receiver_id", user["id"]).limit(1).execute().data)
    if existing:
        return True
    orders = (db.table("orders").select("id").eq("shop_id", shops[0]["id"])
              .eq("buyer_id", partner["id"]).limit(1).execute().data)
    return bool(orders)


def _display_name(profile):
    return profile.get("full_name") or profile.get("username") or "Người dùng"


def _timestamp(value):
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed.replace(tzinfo=timezone.utc) if parsed.tzinfo is None else parsed


def _products_for_messages(db, messages):
    product_ids = {message.get("product_id") for message in messages if message.get("product_id")}
    if not product_ids:
        return {}
    products = (db.table("products").select("id,name,price,shop_id").in_(
        "id", list(product_ids)).limit(MAX_MESSAGES).execute().data)
    if not products:
        return {}
    images = (db.table("product_images").select("product_id,url,is_main,position").in_(
        "product_id", [product["id"] for product in products]).order("position").limit(
            MAX_MESSAGES).execute().data)
    main_images = {}
    for image in images:
        if image.get("is_main") or image["product_id"] not in main_images:
            main_images[image["product_id"]] = image["url"]
    return {
        product["id"]: {
            "id": product["id"],
            "name": product["name"],
            "price": product["price"],
            "image_url": main_images.get(product["id"]),
        }
        for product in products
    }


def _message_views(db, messages):
    products = _products_for_messages(db, messages)
    result = []
    for message in messages:
        item = {key: message.get(key) for key in (
            "id", "sender_id", "receiver_id", "content", "product_id", "created_at")}
        item["product"] = products.get(message.get("product_id"))
        result.append(item)
    return result


@bp.get("/conversations")
@require_role("buyer", "seller")
def conversations():
    """Trả các cuộc trò chuyện có tin nhắn, kèm số tin chưa đọc."""
    db = get_db()
    user_id = g.user["id"]
    sent = (db.table("messages").select("id,sender_id,receiver_id,content,product_id,is_read,created_at")
            .eq("sender_id", user_id).limit(MAX_MESSAGES).execute().data)
    received = (db.table("messages").select("id,sender_id,receiver_id,content,product_id,is_read,created_at")
                .eq("receiver_id", user_id).limit(MAX_MESSAGES).execute().data)
    messages = sent + received
    grouped = {}
    for message in messages:
        other_id = message["receiver_id"] if message["sender_id"] == user_id else message["sender_id"]
        row = grouped.setdefault(other_id, {"messages": [], "unread": 0})
        row["messages"].append(message)
        if message["receiver_id"] == user_id and not message.get("is_read", False):
            row["unread"] += 1

    profiles = _profiles(db, grouped)
    latest_messages = [
        max(conversation["messages"], key=lambda item: _timestamp(item["created_at"]))
        for conversation in grouped.values()
    ]
    products = _products_for_messages(db, latest_messages)
    result = []
    for other_id, conversation in grouped.items():
        partner = profiles.get(other_id)
        if not partner or not _may_chat(db, partner):
            continue
        latest = max(conversation["messages"], key=lambda item: _timestamp(item["created_at"]))
        result.append({
            "user_id": other_id,
            "name": _display_name(partner),
            "avatar_url": partner.get("avatar_url"),
            "role": partner["role"],
            "last_message": latest["content"],
            "last_product": products.get(latest.get("product_id")),
            "last_at": latest["created_at"],
            "unread": conversation["unread"],
        })
    result.sort(key=lambda item: _timestamp(item["last_at"]), reverse=True)
    return ok(result)


@bp.get("/shops")
@require_role("buyer")
def search_shops():
    """GET /api/chat/shops?q=name: tìm shop đang được duyệt để Buyer bắt đầu chat."""
    keyword = catalog.normalize(request.args.get("q") or "").strip()
    if len(keyword) < 2:
        return ok({"items": []})
    if len(keyword) > 80:
        return fail("INVALID_INPUT", "Từ khóa tìm shop tối đa 80 ký tự.", 400)

    db = get_db()
    shops = db.table("shops").select("id,owner_id,name").eq(
        "moderation_status", "approved").limit(1000).execute().data
    matches = [
        shop for shop in shops
        if keyword in catalog.normalize(shop.get("name") or "")
    ]
    owners = _profiles(db, {shop["owner_id"] for shop in matches})
    items = []
    for shop in matches:
        owner = owners.get(shop["owner_id"])
        if owner and owner.get("role") == "seller" and owner.get("status") == "active":
            items.append({
                "shop_id": shop["id"],
                "name": shop["name"],
                "user_id": shop["owner_id"],
            })
            if len(items) == 20:
                break
    return ok({"items": items})


@bp.get("/shops/<int:shop_id>")
@require_role("buyer")
def shop_contact(shop_id):
    """Lấy người nhận chat cho một shop, kể cả khi chưa phát sinh hội thoại."""
    db = get_db()
    shop = _shop(db, shop_id)
    if not shop or shop.get("moderation_status", "approved") != "approved":
        return fail("NOT_FOUND", "Không tìm thấy cửa hàng.", 404)
    partner = _profile(db, shop["owner_id"])
    if not partner or not _may_chat(db, partner):
        return fail("NOT_FOUND", "Không tìm thấy cửa hàng.", 404)
    return ok({"user_id": partner["id"], "name": shop.get("name") or _display_name(partner)})


@bp.get("/messages")
@require_role("buyer", "seller")
def messages():
    """Đọc tin nhắn với một người và đánh dấu tin nhận được là đã đọc."""
    partner_id = (request.args.get("with") or "").strip()
    if not partner_id or len(partner_id) > 100:
        return fail("INVALID_INPUT", "Cuộc trò chuyện không hợp lệ.", 400)
    after = request.args.get("after")
    if after:
        try:
            after_time = _timestamp(after)
        except ValueError:
            return fail("INVALID_INPUT", "Mốc thời gian không hợp lệ.", 400)
    else:
        after_time = None

    db = get_db()
    partner = _profile(db, partner_id)
    if not partner or not _may_chat(db, partner):
        return fail("NOT_FOUND", "Không tìm thấy cuộc trò chuyện.", 404)

    sent = (db.table("messages").select("id,sender_id,receiver_id,content,product_id,is_read,created_at").eq("sender_id", g.user["id"])
            .eq("receiver_id", partner_id).limit(MAX_MESSAGES).execute().data)
    received = (db.table("messages").select("id,sender_id,receiver_id,content,product_id,is_read,created_at").eq("sender_id", partner_id)
                .eq("receiver_id", g.user["id"]).limit(MAX_MESSAGES).execute().data)
    all_messages = sent + received
    if received:
        db.table("messages").update({"is_read": True}).eq("sender_id", partner_id).eq(
            "receiver_id", g.user["id"]).eq("is_read", False).execute()

    filtered_messages = [
        item for item in all_messages
        if after_time is None or _timestamp(item["created_at"]) > after_time
    ]
    filtered_messages.sort(key=lambda item: _timestamp(item["created_at"]))
    return ok(_message_views(db, filtered_messages))


@bp.post("/messages")
@require_role("buyer", "seller")
def send_message():
    """Gửi tin nhắn tới receiver_id; Buyer cũng có thể chỉ định shop_id."""
    body = request.get_json(silent=True) or {}
    content = str(body.get("content") or "").strip()
    if not content or len(content) > MAX_CONTENT_LENGTH:
        return fail("INVALID_INPUT", "Tin nhắn phải có từ 1 đến 2000 ký tự.", 400)

    db = get_db()
    receiver_id = body.get("receiver_id")
    shop_id = None
    if g.user["role"] == "buyer" and body.get("shop_id") is not None:
        try:
            shop_id = int(body["shop_id"])
        except (TypeError, ValueError):
            return fail("INVALID_INPUT", "Cửa hàng không hợp lệ.", 400)
        shop = _shop(db, shop_id)
        if not shop:
            return fail("NOT_FOUND", "Không tìm thấy cửa hàng.", 404)
        shop_id = shop["id"]
        receiver_id = shop["owner_id"]

    partner = _profile(db, receiver_id) if isinstance(receiver_id, str) else None
    if not partner or not _may_chat(db, partner):
        return fail("NOT_FOUND", "Không tìm thấy người nhận.", 404)

    product_id = body.get("product_id")
    product = None
    if product_id is not None:
        if g.user["role"] != "buyer":
            return fail("INVALID_INPUT", "Chỉ Buyer có thể gửi kèm sản phẩm.", 400)
        try:
            product_id = int(product_id)
        except (TypeError, ValueError):
            return fail("INVALID_INPUT", "Sản phẩm không hợp lệ.", 400)
        rows = (db.table("products").select("id,name,price,shop_id").eq(
            "id", product_id).limit(1).execute().data)
        product = rows[0] if rows else None
        shops = (db.table("shops").select("id").eq("owner_id", partner["id"])
                 .limit(1).execute().data)
        expected_shop_id = shop_id if shop_id is not None else (shops[0]["id"] if shops else None)
        if not product or product.get("shop_id") != expected_shop_id:
            return fail("INVALID_INPUT", "Sản phẩm không thuộc cửa hàng đang trò chuyện.", 400)

    created = db.table("messages").insert({
        "sender_id": g.user["id"],
        "receiver_id": partner["id"],
        "content": content,
        "product_id": product_id,
        "is_read": False,
    }).execute().data[0]
    created["product"] = _products_for_messages(db, [created]).get(product_id) if product_id else None
    return ok(created, 201)
