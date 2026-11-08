"""API cho Seller (mục 9.5): xem shop, đơn hàng, đổi trạng thái đơn, thống kê."""
from datetime import datetime, timezone

from flask import Blueprint, current_app, g, request

from ..services import fulfillment, ordering
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import build_order_views
from ..services.responses import fail, ok

bp = Blueprint("seller", __name__, url_prefix="/api/seller")

LOW_STOCK_LIMIT = 5   # sắp hết hàng khi tồn kho từ 5 trở xuống (mục 9.5)
MAX_ORDERS = 200


def _my_shop(db):
    """Shop của Seller đang đăng nhập, hoặc None. Mỗi Seller có đúng một shop."""
    rows = db.table("shops").select("*").eq("owner_id", g.user["id"]).limit(1).execute().data
    return rows[0] if rows else None


def _no_shop():
    return fail("SHOP_NOT_FOUND", "Tài khoản của bạn chưa có shop.", 404)


@bp.get("/shop")
@require_role("seller")
def get_shop():
    """GET /api/seller/shop: thông tin shop của mình."""
    db = get_db()
    shop = _my_shop(db)
    if not shop:
        return _no_shop()
    view = {k: shop.get(k) for k in (
        "id", "name", "description", "address", "lat", "lng", "prep_minutes", "moderation_status")}
    if shop.get("moderation_status") == "rejected":
        # Lý do Admin từ chối nằm ở hàng đợi duyệt (bảng shops không có cột này)
        rows = (db.table("moderation_queue").select("reject_reason").eq("target_type", "shop")
                .eq("target_id", shop["id"]).eq("status", "rejected").order("id", desc=True).limit(1).execute().data)
        view["reject_reason"] = rows[0]["reject_reason"] if rows else None
    return ok(view)


@bp.get("/orders")
@require_role("seller")
def list_orders():
    """GET /api/seller/orders?status=pending|processing|shipping|history. Bỏ status thì trả tất cả."""
    status = request.args.get("status")
    if status and status not in ordering.STATUS_FILTERS:
        return fail("INVALID_INPUT", "Trạng thái không hợp lệ.", 400)

    db = get_db()
    shop = _my_shop(db)
    if not shop:
        return _no_shop()
    query = db.table("orders").select("*").eq("shop_id", shop["id"])
    if status:
        query = query.in_("status", ordering.STATUS_FILTERS[status])
    orders = query.order("created_at", desc=True).limit(MAX_ORDERS).execute().data
    return ok({"items": build_order_views(db, orders, with_buyer=True)})


@bp.patch("/orders/<int:order_id>/status")
@require_role("seller")
def update_order_status(order_id):
    """PATCH /api/seller/orders/{id}/status { status }: đổi trạng thái theo mục 10.1.

    pending -> processing: trừ tồn kho (thiếu hàng thì 409).
    processing -> cancelled: hoàn lại tồn kho.
    shipping -> completed: tăng sold_count, ghi sự kiện purchase, COD đặt đã thanh toán.
    """
    body = request.get_json(silent=True) or {}
    new_status = body.get("status")
    if new_status not in ordering.ORDER_STATUSES:
        return fail("INVALID_INPUT", "Trạng thái không hợp lệ.", 400)

    db = get_db()
    shop = _my_shop(db)
    if not shop:
        return _no_shop()
    rows = db.table("orders").select("*").eq("id", order_id).eq("shop_id", shop["id"]).limit(1).execute().data
    if not rows:  # đơn của shop khác cũng trả 404 để không lộ sự tồn tại
        return fail("NOT_FOUND", "Không tìm thấy đơn hàng.", 404)
    order = rows[0]

    try:
        ordering.check_seller_transition(order["status"], new_status)
    except ordering.OrderError as err:
        return fail(err.code, err.message, err.status)

    items = db.table("order_items").select("*").eq("order_id", order_id).execute().data
    fields = {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}
    if new_status == "completed" and order["payment_status"] == "unpaid":
        fields["payment_status"] = "paid"  # COD thu tiền khi giao xong

    deducted, status_saved = [], False
    try:
        if order["status"] == "pending" and new_status == "processing":
            deducted = fulfillment.deduct_stock(db, items)
        # Điều kiện "status vẫn như cũ" chặn hai lần bấm cùng lúc cùng xử lý một đơn
        updated_rows = db.table("orders").update(fields).eq("id", order_id).eq("status", order["status"]).execute().data
        if not updated_rows:
            fulfillment.add_stock(db, deducted)
            return fail("CONFLICT", "Đơn vừa được cập nhật bởi thao tác khác, vui lòng tải lại.", 409)
        status_saved = True
        updated = updated_rows[0]

        if order["status"] == "processing" and new_status == "cancelled":
            fulfillment.add_stock(db, fulfillment.stock_pairs(items))
        if new_status == "completed":
            fulfillment.record_completion(db, updated, items)
    except ordering.OrderError as err:
        return fail(err.code, err.message, err.status)
    except Exception:
        current_app.logger.exception("Đổi trạng thái đơn %s thất bại", order_id)
        if deducted and not status_saved:
            fulfillment.add_stock(db, deducted)  # chưa đổi được trạng thái thì trả lại số vừa trừ
        return fail("SERVER_ERROR", "Không cập nhật được đơn hàng, vui lòng thử lại.", 500)

    return ok(build_order_views(db, [updated], with_buyer=True)[0])


@bp.get("/stats")
@require_role("seller")
def stats():
    """GET /api/seller/stats: số đơn theo trạng thái, tồn kho, đã bán, sản phẩm chờ duyệt, sắp hết hàng."""
    db = get_db()
    shop = _my_shop(db)
    if not shop:
        return _no_shop()

    orders = db.table("orders").select("id,status").eq("shop_id", shop["id"]).execute().data
    by_status = {s: 0 for s in ordering.ORDER_STATUSES}
    for order in orders:
        by_status[order["status"]] += 1

    products = db.table("products").select("id,name,sold_count,moderation_status,is_active").eq("shop_id", shop["id"]).execute().data
    active = {p["id"]: p for p in products if p["is_active"]}
    variants = []
    if active:
        variants = db.table("product_variants").select("id,product_id,size,color,stock").in_("product_id", list(active)).execute().data

    low_stock = sorted(
        ({"product_id": v["product_id"], "name": active[v["product_id"]]["name"],
          "size": v["size"], "color": v["color"], "stock": v["stock"]}
         for v in variants
         if v["stock"] <= LOW_STOCK_LIMIT and active[v["product_id"]]["moderation_status"] == "approved"),
        key=lambda row: (row["stock"], row["name"]))

    return ok({
        "orders_by_status": by_status,
        "total_stock": sum(v["stock"] for v in variants),
        "total_sold": sum(p["sold_count"] for p in products),
        "pending_products": sum(1 for p in products if p["moderation_status"] == "pending"),
        "low_stock": low_stock[:20],
    })