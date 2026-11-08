"""Giỏ hàng của Buyer (mục 9.2): xem, thêm, đổi số lượng, xóa."""
from flask import Blueprint, g, request

from ..services import catalog
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import fetch_by_ids, fetch_product_rows
from ..services.responses import fail, ok

bp = Blueprint("cart", __name__, url_prefix="/api/cart")

MAX_QTY = 99  # chặn số lượng vô lý


def _stock_error(stock):
    """Thông báo vượt tồn kho (409 OUT_OF_STOCK)."""
    if stock <= 0:
        return fail("OUT_OF_STOCK", "Sản phẩm này đã hết hàng.", 409)
    return fail("OUT_OF_STOCK", f"Chỉ còn {stock} sản phẩm trong kho.", 409)


def _is_sellable(product):
    """Sản phẩm đang được bán: đã duyệt và chưa bị ẩn."""
    return bool(product) and product["moderation_status"] == "approved" and product["is_active"]


@bp.get("")
@require_role("buyer")
def get_cart():
    """GET /api/cart: các dòng giỏ kèm thẻ sản phẩm, size, màu, tồn kho và tổng tiền."""
    db = get_db()
    items = db.table("cart_items").select("id,variant_id,quantity").eq("user_id", g.user["id"]).order("id").execute().data
    variants = fetch_by_ids(db, "product_variants", [i["variant_id"] for i in items], "id,product_id,size,color,stock")
    products = fetch_product_rows(db, [v["product_id"] for v in variants.values()])

    result, total = [], 0
    for item in items:
        variant = variants.get(item["variant_id"])
        product = products.get(variant["product_id"]) if variant else None
        if not variant or not product:
            continue
        card = catalog.build_card(product)
        available = _is_sellable(product)
        if available:
            total += card["price"] * item["quantity"]
        result.append({
            "id": item["id"], "variant_id": item["variant_id"], "quantity": item["quantity"],
            "product": card, "size": variant["size"], "color": variant["color"],
            "stock": variant["stock"], "available": available,
        })
    return ok({"items": result, "total": total})


@bp.post("/items")
@require_role("buyer")
def add_item():
    """POST /api/cart/items { variant_id, quantity }: đã có trong giỏ thì cộng dồn."""
    body = request.get_json(silent=True) or {}
    variant_id = catalog.parse_int(body.get("variant_id"))
    quantity = catalog.parse_int(body.get("quantity"), 1)
    if variant_id is None or quantity is None or not 1 <= quantity <= MAX_QTY:
        return fail("INVALID_INPUT", f"Số lượng phải từ 1 đến {MAX_QTY}.", 400)

    db = get_db()
    variants = db.table("product_variants").select("id,product_id,size,color,stock").eq("id", variant_id).limit(1).execute().data
    if not variants:
        return fail("NOT_FOUND", "Không tìm thấy phân loại sản phẩm.", 404)
    variant = variants[0]
    product = fetch_by_ids(db, "products", [variant["product_id"]], "id,name,moderation_status,is_active").get(variant["product_id"])
    if not _is_sellable(product):
        return fail("PRODUCT_UNAVAILABLE", "Sản phẩm này hiện không được bán.", 422)

    existing = db.table("cart_items").select("id,quantity").eq("user_id", g.user["id"]).eq("variant_id", variant_id).limit(1).execute().data
    new_quantity = quantity + (existing[0]["quantity"] if existing else 0)
    if new_quantity > variant["stock"]:
        return _stock_error(variant["stock"])

    if existing:
        db.table("cart_items").update({"quantity": new_quantity}).eq("id", existing[0]["id"]).execute()
        return ok({"id": existing[0]["id"], "variant_id": variant_id, "quantity": new_quantity})
    row = db.table("cart_items").insert(
        {"user_id": g.user["id"], "variant_id": variant_id, "quantity": new_quantity}).execute().data[0]
    return ok({"id": row["id"], "variant_id": variant_id, "quantity": new_quantity}, 201)


def _own_item(db, item_id):
    """Dòng giỏ thuộc về người dùng hiện tại, hoặc None (người khác không chạm được giỏ của mình)."""
    rows = db.table("cart_items").select("id,variant_id,quantity").eq("id", item_id).eq("user_id", g.user["id"]).limit(1).execute().data
    return rows[0] if rows else None


@bp.patch("/items/<int:item_id>")
@require_role("buyer")
def update_item(item_id):
    """PATCH /api/cart/items/{id} { quantity }."""
    body = request.get_json(silent=True) or {}
    quantity = catalog.parse_int(body.get("quantity"))
    if quantity is None or not 1 <= quantity <= MAX_QTY:
        return fail("INVALID_INPUT", f"Số lượng phải từ 1 đến {MAX_QTY}.", 400)

    db = get_db()
    item = _own_item(db, item_id)
    if not item:
        return fail("NOT_FOUND", "Không tìm thấy mục trong giỏ hàng.", 404)
    variant = fetch_by_ids(db, "product_variants", [item["variant_id"]], "id,stock").get(item["variant_id"])
    if not variant or quantity > variant["stock"]:
        return _stock_error(variant["stock"] if variant else 0)

    db.table("cart_items").update({"quantity": quantity}).eq("id", item_id).execute()
    return ok({"id": item_id, "variant_id": item["variant_id"], "quantity": quantity})


@bp.delete("/items/<int:item_id>")
@require_role("buyer")
def delete_item(item_id):
    """DELETE /api/cart/items/{id}."""
    db = get_db()
    if not _own_item(db, item_id):
        return fail("NOT_FOUND", "Không tìm thấy mục trong giỏ hàng.", 404)
    db.table("cart_items").delete().eq("id", item_id).execute()
    return ok({})