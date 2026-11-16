"""Đơn hàng của Buyer (mục 9.3): đặt hàng, danh sách, chi tiết, hủy."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, request

from ..services import catalog, ordering, vietqr
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import build_order_views as _build_views, fetch_by_ids, fetch_main_images
from ..services.responses import fail, ok
from .me import PHONE_RE

bp = Blueprint("orders", __name__, url_prefix="/api/orders")

PAYMENT_METHODS = ("cod", "mock_card", "bank_transfer")
MAX_CHECKOUT_ITEMS = 50


def _optional_float(value, low, high):
    """Đổi sang số thực trong khoảng [low, high]. Trả về (giá trị, hợp lệ?)."""
    if value is None:
        return None, True
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None, False
    return (number, True) if low <= number <= high else (None, False)


def _own_order(db, order_id):
    """Đơn thuộc về người mua hiện tại, hoặc None."""
    rows = db.table("orders").select("*").eq("id", order_id).eq("buyer_id", g.user["id"]).limit(1).execute().data
    return rows[0] if rows else None


@bp.post("/checkout")
@require_role("buyer")
def checkout():
    """POST /api/orders/checkout: tách đơn theo shop, kiểm tra tồn kho, tạo đơn, xóa mục đã đặt khỏi giỏ."""
    body = request.get_json(silent=True) or {}

    raw_ids = body.get("cart_item_ids")
    if not isinstance(raw_ids, list) or not raw_ids or len(raw_ids) > MAX_CHECKOUT_ITEMS:
        return fail("INVALID_INPUT", "Vui lòng chọn ít nhất 1 sản phẩm để thanh toán.", 400)
    ids = [catalog.parse_int(i) for i in raw_ids]
    if any(i is None or i <= 0 for i in ids):
        return fail("INVALID_INPUT", "Danh sách sản phẩm không hợp lệ.", 400)
    ids = sorted(set(ids))

    receiver = str(body.get("receiver_name") or "").strip()
    phone = str(body.get("phone") or "").replace(" ", "")
    address = str(body.get("address") or "").strip()
    payment = body.get("payment_method")
    if not receiver or len(receiver) > 100:
        return fail("INVALID_INPUT", "Vui lòng nhập tên người nhận (tối đa 100 ký tự).", 400)
    if not PHONE_RE.match(phone):
        return fail("INVALID_INPUT", "Số điện thoại không hợp lệ.", 400)
    if not address or len(address) > 255:
        return fail("INVALID_INPUT", "Vui lòng nhập địa chỉ nhận hàng (tối đa 255 ký tự).", 400)
    if payment not in PAYMENT_METHODS:
        return fail("INVALID_INPUT", "Phương thức thanh toán không hợp lệ.", 400)
    payment_settings = None
    if payment == "bank_transfer":
        try:
            payment_settings = vietqr.payment_settings()
        except ValueError as err:
            return fail("PAYMENT_NOT_CONFIGURED", str(err), 503)
    lat, lat_ok = _optional_float(body.get("lat"), -90, 90)
    lng, lng_ok = _optional_float(body.get("lng"), -180, 180)
    if not (lat_ok and lng_ok):
        return fail("INVALID_INPUT", "Vị trí giao hàng không hợp lệ.", 400)
    if lat is None or lng is None:  # chỉ tính ETA khi có đủ cả hai tọa độ
        lat = lng = None

    db = get_db()
    cart_rows = db.table("cart_items").select("id,variant_id,quantity").eq("user_id", g.user["id"]).in_("id", ids).execute().data
    if len(cart_rows) != len(ids):
        return fail("CART_CHANGED", "Giỏ hàng đã thay đổi, vui lòng tải lại trang.", 409)

    variants = fetch_by_ids(db, "product_variants", [r["variant_id"] for r in cart_rows], "id,product_id,size,color,stock")
    products = fetch_by_ids(db, "products", [v["product_id"] for v in variants.values()],
                            "id,name,price,shop_id,moderation_status,is_active")
    shops = fetch_by_ids(db, "shops", [p["shop_id"] for p in products.values()], "id,name,lat,lng,prep_minutes,address")

    try:
        plans = ordering.plan_checkout(cart_rows, variants, products, shops, lat, lng)
    except ordering.OrderError as err:
        return fail(err.code, err.message, err.status)

    # supabase-py gọi từng lệnh REST nên không có transaction: lỗi giữa chừng thì xóa các đơn vừa tạo
    created = []
    try:
        for plan in plans:
            order = db.table("orders").insert({
                "buyer_id": g.user["id"], "shop_id": plan["shop_id"], "total": plan["total"],
                "payment_method": payment, "payment_status": "paid" if payment == "mock_card" else "unpaid",
                "receiver_name": receiver, "phone": phone, "address": address,
                "lat": lat, "lng": lng, "eta_minutes": plan["eta_minutes"],
            }).execute().data[0]
            created.append((order, plan))
            db.table("order_items").insert(
                [dict(item, order_id=order["id"]) for item in plan["items"]]).execute()
        payment_info = vietqr.instructions_for_orders(
            [order for order, _ in created], payment_settings) if payment_settings else None
        db.table("cart_items").delete().in_("id", ids).execute()
    except Exception:
        current_app.logger.exception("Đặt hàng thất bại, hoàn tác các đơn đã tạo")
        for order, _ in created:
            db.table("orders").delete().eq("id", order["id"]).execute()  # order_items xóa theo (on delete cascade)
        return fail("ORDER_FAILED", "Không đặt được hàng, vui lòng thử lại.", 500)

    images = fetch_main_images(db, [i["product_id"] for _, plan in created for i in plan["items"]])
    views = [ordering.order_view(order, shops.get(plan["shop_id"]), plan["items"], images) for order, plan in created]
    return ok({"orders": views, "payment": payment_info}, 201)


@bp.post("/<int:order_id>/payment-report")
@require_role("buyer")
def report_transfer(order_id):
    """Buyer reports a bank transfer; payment remains unverified until Admin reconciles it."""
    db = get_db()
    order = _own_order(db, order_id)
    if not order:
        return fail("NOT_FOUND", "Không tìm thấy đơn hàng.", 404)
    if order["payment_method"] != "bank_transfer":
        return fail("INVALID_PAYMENT", "Đơn hàng này không dùng chuyển khoản QR.", 422)
    if order["status"] == "cancelled":
        return fail("INVALID_STATE", "Không thể báo thanh toán cho đơn đã hủy.", 422)
    if order["payment_status"] == "reported":
        return ok({"id": order_id, "payment_status": "reported"})
    if order["payment_status"] != "unpaid":
        return fail("INVALID_STATE", "Trạng thái thanh toán của đơn không thể thay đổi.", 422)

    updated = (db.table("orders").update({"payment_status": "reported"})
               .eq("id", order_id).eq("buyer_id", g.user["id"])
               .eq("payment_status", "unpaid").eq("status", order["status"]).execute().data)
    if not updated:
        return fail("CONFLICT", "Đơn hàng vừa được cập nhật, vui lòng tải lại.", 409)
    return ok({"id": order_id, "payment_status": "reported"})


@bp.get("/<int:order_id>/payment-instructions")
@require_role("buyer")
def payment_instructions(order_id):
    """Buyer reopens the QR for an unpaid or reported bank transfer."""
    db = get_db()
    order = _own_order(db, order_id)
    if not order:
        return fail("NOT_FOUND", "Không tìm thấy đơn hàng.", 404)
    if order["payment_method"] != "bank_transfer" or order["payment_status"] == "paid":
        return fail("INVALID_PAYMENT", "Đơn hàng này không cần thanh toán chuyển khoản.", 422)
    if order["status"] == "cancelled":
        return fail("INVALID_STATE", "Không thể thanh toán đơn đã hủy.", 422)
    try:
        settings = vietqr.payment_settings()
    except ValueError as err:
        return fail("PAYMENT_NOT_CONFIGURED", str(err), 503)
    return ok(vietqr.instructions_for_orders([order], settings))


@bp.get("")
@require_role("buyer")
def list_orders():
    """GET /api/orders?status=pending|processing|shipping|history. Bỏ status thì trả tất cả, mới nhất trước."""
    status = request.args.get("status")
    query = get_db().table("orders").select("*").eq("buyer_id", g.user["id"])
    if status:
        if status not in ordering.STATUS_FILTERS:
            return fail("INVALID_INPUT", "Trạng thái không hợp lệ.", 400)
        query = query.in_("status", ordering.STATUS_FILTERS[status])
    orders = query.order("created_at", desc=True).limit(100).execute().data
    return ok({"items": _build_views(get_db(), orders)})


@bp.get("/<int:order_id>")
@require_role("buyer")
def order_detail(order_id):
    """GET /api/orders/{id}: chi tiết đơn kèm thông tin shop."""
    db = get_db()
    order = _own_order(db, order_id)
    if not order:
        return fail("NOT_FOUND", "Không tìm thấy đơn hàng.", 404)
    view = _build_views(db, [order])[0]
    shop = fetch_by_ids(db, "shops", [order["shop_id"]], "id,name,lat,lng,address").get(order["shop_id"]) or {}
    view["shop"] = {k: shop.get(k) for k in ("name", "lat", "lng", "address")}
    return ok(view)


@bp.post("/<int:order_id>/cancel")
@require_role("buyer")
def cancel_order(order_id):
    """POST /api/orders/{id}/cancel: chỉ hủy được khi đơn còn chờ xác nhận (chưa trừ tồn kho nên không cần hoàn)."""
    db = get_db()
    order = _own_order(db, order_id)
    if not order:
        return fail("NOT_FOUND", "Không tìm thấy đơn hàng.", 404)
    if order["status"] != "pending":
        return fail("INVALID_STATE", "Chỉ hủy được đơn đang chờ xác nhận.", 422)
    updated = db.table("orders").update({
        "status": "cancelled", "updated_at": datetime.now(timezone.utc).isoformat(),
    }).eq("id", order_id).execute().data[0]
    return ok(_build_views(db, [updated])[0])