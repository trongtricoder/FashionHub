"""Xử lý kho và thống kê khi đơn đổi trạng thái (mục 10.1): trừ tồn, hoàn tồn, ghi nhận bán hàng."""
from .ordering import OrderError
from .queries import fetch_by_ids

MAX_RETRIES = 3  # số lần thử lại khi tồn kho bị thay đổi bởi thao tác khác


def _wanted_per_variant(items):
    """Gom số lượng cần theo từng biến thể. Ném OrderError nếu có dòng đã mất biến thể (bị xóa)."""
    wanted = {}
    for item in items:
        if item.get("variant_id") is None:
            raise OrderError("PRODUCT_UNAVAILABLE",
                             f"{item['product_name']} không còn tồn tại trong kho dữ liệu.", 422)
        wanted[item["variant_id"]] = wanted.get(item["variant_id"], 0) + item["quantity"]
    return wanted


def deduct_stock(db, items):
    """Trừ tồn kho cho các dòng của đơn khi Seller xác nhận.

    Kiểm tra đủ hàng trước, rồi trừ từng biến thể kèm điều kiện "tồn kho chưa đổi" để hai đơn xác nhận
    cùng lúc không trừ chồng. Lỗi giữa chừng thì hoàn lại phần đã trừ. Trả về danh sách (variant_id, số lượng) đã trừ.
    """
    wanted = _wanted_per_variant(items)
    variants = fetch_by_ids(db, "product_variants", list(wanted), "id,stock")
    names = {i["variant_id"]: f"{i['product_name']} (size {i.get('size')}, màu {i.get('color')})" for i in items}

    for variant_id, qty in wanted.items():
        variant = variants.get(variant_id)
        if not variant or variant["stock"] < qty:
            have = variant["stock"] if variant else 0
            raise OrderError("OUT_OF_STOCK", f"{names[variant_id]} chỉ còn {have} trong kho, đơn cần {qty}.", 409)

    done = []
    try:
        for variant_id, qty in wanted.items():
            current = variants[variant_id]["stock"]
            rows = (db.table("product_variants").update({"stock": current - qty})
                    .eq("id", variant_id).eq("stock", current).execute().data)
            if not rows:
                raise OrderError("STOCK_CONFLICT", "Tồn kho vừa thay đổi do thao tác khác, vui lòng thử lại.", 409)
            done.append((variant_id, qty))
    except Exception:
        add_stock(db, done)
        raise
    return done


def add_stock(db, pairs):
    """Cộng lại tồn kho cho các cặp (variant_id, số lượng). Biến thể đã bị xóa thì bỏ qua."""
    for variant_id, qty in pairs:
        for _ in range(MAX_RETRIES):
            rows = db.table("product_variants").select("id,stock").eq("id", variant_id).limit(1).execute().data
            if not rows:
                break
            stock = rows[0]["stock"]
            if db.table("product_variants").update({"stock": stock + qty}).eq("id", variant_id).eq("stock", stock).execute().data:
                break


def stock_pairs(items):
    """Các cặp (variant_id, số lượng) của đơn, bỏ dòng đã mất biến thể."""
    pairs = {}
    for item in items:
        if item.get("variant_id") is not None:
            pairs[item["variant_id"]] = pairs.get(item["variant_id"], 0) + item["quantity"]
    return list(pairs.items())


def record_completion(db, order, items):
    """Đơn hoàn tất: tăng sold_count của sản phẩm và ghi sự kiện purchase cho dashboard."""
    sold = {}
    for item in items:
        if item.get("product_id") is not None:
            sold[item["product_id"]] = sold.get(item["product_id"], 0) + item["quantity"]
    for product_id, qty in sold.items():
        for _ in range(MAX_RETRIES):
            row = db.table("products").select("id,sold_count").eq("id", product_id).limit(1).execute().data
            if not row:
                break
            current = row[0]["sold_count"]
            if db.table("products").update({"sold_count": current + qty}).eq("id", product_id).eq("sold_count", current).execute().data:
                break
    events = [
        {"shop_id": order["shop_id"], "product_id": item.get("product_id"),
         "user_id": order["buyer_id"], "event_type": "purchase"}
        for item in items
    ]
    if events:
        db.table("analytics_events").insert(events).execute()