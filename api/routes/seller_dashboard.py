"""Dashboard của Seller (mục 9.5): GET /api/seller/dashboard."""
from flask import Blueprint, g, request

from ai.seller import stats

from ..services import seller_data
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import shop_of_owner
from ..services.responses import fail, ok

bp = Blueprint("seller_dashboard", __name__, url_prefix="/api/seller")


@bp.get("/dashboard")
@require_role("seller")
def dashboard():
    """GET /api/seller/dashboard?range=7d|30d|12m: lượt xem, doanh thu, đơn theo ngày (hoặc tháng), KPI, dự đoán."""
    range_key = request.args.get("range", "30d")
    if range_key not in stats.RANGES:
        return fail("INVALID_INPUT", "Khoảng thời gian chỉ có thể là 7d, 30d hoặc 12m.", 400)
    db = get_db()
    shop = shop_of_owner(db, g.user["id"])
    if not shop:
        return fail("SHOP_NOT_FOUND", "Tài khoản của bạn chưa có shop.", 404)
    return ok(seller_data.dashboard_data(db, shop, range_key, seller_data.today_vn()))