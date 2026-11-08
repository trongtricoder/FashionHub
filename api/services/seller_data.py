"""Gom dữ liệu thật của một shop cho dashboard, gợi ý và trợ lý AI (mục 9.5, 10.5).

Phần tính toán nằm ở ai/seller/ (hàm thuần). File này chỉ lo lấy dữ liệu từ database và đổi thành đầu vào cho chúng.
"""
from datetime import datetime, timedelta

from ai.seller import forecast as forecast_ai
from ai.seller import stats

from .queries import fetch_all, fetch_in_chunks


def today_vn():
    """Hôm nay theo giờ Việt Nam. Tách thành hàm riêng để test có thể cố định ngày."""
    return datetime.now(stats.VN_TZ).date()


def shop_totals(db, shop_id):
    """(tổng đã bán, tổng tồn kho) của các sản phẩm đang hiển thị trong shop."""
    products = db.table("products").select("id,sold_count").eq("shop_id", shop_id).eq("is_active", True).execute().data
    variants = fetch_in_chunks(db, "product_variants", "product_id", [p["id"] for p in products], "id,stock")
    return sum(p["sold_count"] for p in products), sum(v["stock"] for v in variants)


def completed_orders_since(db, shop_id, since_iso):
    """Các đơn hoàn tất từ mốc since_iso, dạng (ngày hoàn tất theo giờ Việt Nam, tổng tiền)."""
    rows = fetch_all(lambda: (
        db.table("orders").select("id,total,updated_at").eq("shop_id", shop_id)
        .eq("status", "completed").gte("updated_at", since_iso).order("id")))
    return [(stats.vn_date(r["updated_at"]), r["total"]) for r in rows]


def dashboard_data(db, shop, range_key, today):
    """Dữ liệu cho GET /api/seller/dashboard."""
    start_day = stats.range_start(range_key, today)
    since = stats.start_utc_iso(start_day)

    view_rows = fetch_all(lambda: (
        db.table("analytics_events").select("created_at").eq("shop_id", shop["id"])
        .eq("event_type", "view").gte("created_at", since).order("id")))
    view_dates = [stats.vn_date(r["created_at"]) for r in view_rows]
    completed = completed_orders_since(db, shop["id"], since)

    forecast = None
    if range_key != "12m":   # xem theo tháng thì không dự đoán (mục 9.5)
        history_start = today - timedelta(days=forecast_ai.HISTORY_DAYS - 1)
        history = completed if start_day <= history_start else completed_orders_since(
            db, shop["id"], stats.start_utc_iso(history_start))
        by_day = {}
        for day, total in history:
            by_day[day] = by_day.get(day, 0) + total
        forecast = forecast_ai.forecast_revenue(by_day, today)

    total_sold, total_stock = shop_totals(db, shop["id"])
    return stats.build_dashboard(range_key, today, view_dates, completed, total_sold, total_stock, forecast)


def insight_context(db, shop, today):
    """Gom số liệu 30 ngày gần nhất của shop thành dict `ctx` cho ai/seller/insights.py và chat.py."""
    sid = shop["id"]
    day30 = today - timedelta(days=29)
    day14 = today - timedelta(days=13)
    since30 = stats.start_utc_iso(day30)

    products = db.table("products").select("id,name,sold_count,moderation_status").eq("shop_id", sid).eq("is_active", True).execute().data
    approved = {p["id"]: p for p in products if p["moderation_status"] == "approved"}
    variants = fetch_in_chunks(db, "product_variants", "product_id", [p["id"] for p in products], "id,product_id,size,color,stock")

    orders = fetch_all(lambda: (
        db.table("orders").select("id,status,buyer_id,created_at,updated_at,total").eq("shop_id", sid)
        .gte("updated_at", since30).order("id")))
    status_rows = fetch_all(lambda: db.table("orders").select("id,status").eq("shop_id", sid).order("id"))
    orders_by_status = {}
    for row in status_rows:
        orders_by_status[row["status"]] = orders_by_status.get(row["status"], 0) + 1

    # Doanh thu theo ngày hoàn tất
    revenue_last7 = revenue_prev7 = revenue_30d = 0
    for order in orders:
        if order["status"] != "completed":
            continue
        age = (today - stats.vn_date(order["updated_at"])).days
        if 0 <= age <= 29:
            revenue_30d += order["total"]
        if 0 <= age <= 6:
            revenue_last7 += order["total"]
        elif 7 <= age <= 13:
            revenue_prev7 += order["total"]

    # Số lượng bán theo sản phẩm (30 ngày) và theo biến thể (14 ngày): tính các đơn đặt trong khoảng và chưa hủy
    selling = {o["id"]: stats.vn_date(o["created_at"]) for o in orders if o["status"] != "cancelled"
               and stats.vn_date(o["created_at"]) >= day30}
    items = fetch_in_chunks(db, "order_items", "order_id", list(selling), "order_id,product_id,variant_id,quantity")
    sold_30d, sold_14d = {}, {}
    for item in items:
        sold_30d[item["product_id"]] = sold_30d.get(item["product_id"], 0) + item["quantity"]
        if selling[item["order_id"]] >= day14:
            sold_14d[item["variant_id"]] = sold_14d.get(item["variant_id"], 0) + item["quantity"]

    events = fetch_all(lambda: (
        db.table("analytics_events").select("product_id,event_type").eq("shop_id", sid)
        .in_("event_type", ["view", "purchase"]).gte("created_at", since30).order("id")))
    views, purchases = {}, {}
    for event in events:
        target = views if event["event_type"] == "view" else purchases
        target[event["product_id"]] = target.get(event["product_id"], 0) + 1

    # Dáng người của những người đã mua trong 30 ngày (mỗi người tính một lần)
    buyer_ids = {o["buyer_id"] for o in orders if o["id"] in selling}
    shapes = fetch_in_chunks(db, "body_profiles", "user_id", buyer_ids, "user_id,body_shape")
    shape_counts = {}
    for row in shapes:
        if row.get("body_shape"):
            shape_counts[row["body_shape"]] = shape_counts.get(row["body_shape"], 0) + 1

    stock_by_product = {}
    for v in variants:
        stock_by_product[v["product_id"]] = stock_by_product.get(v["product_id"], 0) + v["stock"]

    return {
        "today": today,
        "products": [{
            "id": p["id"], "name": p["name"], "stock_total": stock_by_product.get(p["id"], 0),
            "sold_30d": sold_30d.get(p["id"], 0), "views_30d": views.get(p["id"], 0),
            "purchases_30d": purchases.get(p["id"], 0),
        } for p in approved.values()],
        "variants": [{
            "variant_id": v["id"], "product_id": v["product_id"], "name": approved[v["product_id"]]["name"],
            "size": v["size"], "color": v["color"], "stock": v["stock"], "sold_14d": sold_14d.get(v["id"], 0),
        } for v in variants if v["product_id"] in approved],
        "revenue_last7": revenue_last7, "revenue_prev7": revenue_prev7, "revenue_30d": revenue_30d,
        "orders_by_status": orders_by_status,
        "total_stock": sum(v["stock"] for v in variants),
        "shape_counts": shape_counts,
    }