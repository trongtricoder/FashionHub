"""Ghi sự kiện phân tích (mục 9.2): lượt xem và thêm giỏ hàng, phục vụ dashboard Seller."""
from flask import Blueprint, current_app, request

from ..services import catalog
from ..services.auth import optional_user_id
from ..services.db import get_db
from ..services.responses import fail, ok

bp = Blueprint("events", __name__, url_prefix="/api/events")


@bp.post("")
def log_event():
    """POST /api/events { shop_id, product_id?, event_type: view | add_to_cart }. Sự kiện purchase do server tự ghi."""
    body = request.get_json(silent=True) or {}
    shop_id = catalog.parse_int(body.get("shop_id"))
    product_id = catalog.parse_int(body.get("product_id"))
    event_type = body.get("event_type")
    if shop_id is None or event_type not in ("view", "add_to_cart"):
        return fail("INVALID_INPUT", "Sự kiện không hợp lệ.", 400)

    row = {"shop_id": shop_id, "event_type": event_type, "user_id": optional_user_id()}
    if product_id is not None:
        row["product_id"] = product_id
    try:
        get_db().table("analytics_events").insert(row).execute()
    except Exception:  # shop hoặc sản phẩm không tồn tại (vi phạm khóa ngoại)
        current_app.logger.warning("Ghi sự kiện thất bại", exc_info=True)
        return fail("INVALID_INPUT", "Sự kiện không hợp lệ.", 400)
    return ok({}, 201)