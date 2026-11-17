"""Logic đặt hàng thuần Python (không gọi database) để dễ test và dễ giải thích."""
from . import catalog, eta

# Bộ lọc trạng thái của GET /api/orders (mục 9.3). "history" gồm hoàn tất và đã hủy
STATUS_FILTERS = {
    "pending": ["pending"],
    "processing": ["processing"],
    "shipping": ["shipping"],
    "history": ["completed", "cancelled"],
}


ORDER_STATUSES = ("pending", "processing", "shipping", "completed", "cancelled")
PLATFORM_FEE_RATE = 7

# Seller chuyển trạng thái theo mục 10.1: pending -> processing -> shipping -> completed,
# và được hủy khi đơn đang pending hoặc processing (shipping thì không hủy được)
SELLER_TRANSITIONS = {
    "pending": ("processing", "cancelled"),
    "processing": ("shipping", "cancelled"),
    "shipping": ("completed",),
}

STATUS_LABELS = {
    "pending": "chờ xác nhận", "processing": "đang xử lý", "shipping": "đang giao",
    "completed": "hoàn tất", "cancelled": "đã hủy",
}


class OrderError(Exception):
    """Lỗi nghiệp vụ khi đặt hàng, mang theo mã lỗi và mã HTTP."""

    def __init__(self, code, message, status):
        super().__init__(message)
        self.code, self.message, self.status = code, message, status


def platform_fee(total):
    """Tính phí nền tảng theo 7%, làm tròn đến đồng gần nhất."""
    return (total * PLATFORM_FEE_RATE + 50) // 100


def plan_checkout(cart_rows, variants, products, shops, lat=None, lng=None):
    """Kiểm tra giỏ rồi tách thành các đơn, mỗi shop một đơn.

    cart_rows: các dòng cart_items được chọn. variants, products, shops: dict tra theo id.
    Trả về danh sách kế hoạch đơn: { shop_id, total, eta_minutes, items[], cart_item_ids[] }.
    Ném OrderError nếu có sản phẩm ngừng bán hoặc vượt tồn kho.
    """
    groups = {}
    for row in cart_rows:
        variant = variants.get(row["variant_id"])
        product = products.get(variant["product_id"]) if variant else None
        if not product or product["moderation_status"] != "approved" or not product["is_active"]:
            raise OrderError("PRODUCT_UNAVAILABLE",
                             "Có sản phẩm trong giỏ không còn được bán, vui lòng xóa khỏi giỏ.", 422)
        if row["quantity"] > variant["stock"]:
            raise OrderError(
                "OUT_OF_STOCK",
                f"{product['name']} (size {variant['size']}, màu {variant['color']}) "
                f"chỉ còn {variant['stock']} sản phẩm.", 409)
        group = groups.setdefault(
            product["shop_id"],
            {"shop_id": product["shop_id"], "total": 0, "items": [], "cart_item_ids": []})
        group["items"].append({
            "variant_id": variant["id"], "product_id": product["id"],
            "product_name": product["name"], "size": variant["size"], "color": variant["color"],
            "quantity": row["quantity"], "price": product["price"],
        })
        group["total"] += product["price"] * row["quantity"]
        group["cart_item_ids"].append(row["id"])

    plans = []
    for shop_id in sorted(groups):
        group = groups[shop_id]
        shop = shops.get(shop_id) or {}
        group["eta_minutes"] = eta.eta_minutes(
            shop.get("prep_minutes", 60), shop.get("lat"), shop.get("lng"), lat, lng)
        plans.append(group)
    return plans


def items_summary(items):
    """Tóm tắt sản phẩm của đơn, ví dụ: 'Áo thun basic x2, Quần jeans x1'."""
    return ", ".join(f"{i['product_name']} x{i['quantity']}" for i in items)


def order_view(order, shop, items, images):
    """Dựng đơn hàng trả về cho giao diện (mục 9.3).

    Thêm items[] và distance_km (ngoài hợp đồng gốc) để giao diện cũ hiển thị được ngay.
    """
    shop = shop or {}
    distance = eta.road_distance_km(shop.get("lat"), shop.get("lng"), order.get("lat"), order.get("lng"))
    return {
        "id": order["id"],
        "shop_id": order["shop_id"],
        "shop_name": shop.get("name"),
        "total": order["total"],
        "status": order["status"],
        "payment_method": order["payment_method"],
        "payment_status": order["payment_status"],
        "receiver_name": order["receiver_name"],
        "phone": order["phone"],
        "address": order["address"],
        "lat": order.get("lat"),
        "lng": order.get("lng"),
        "eta_minutes": order.get("eta_minutes"),
        "expected_at": eta.expected_at(order.get("created_at"), order.get("eta_minutes")),
        "created_at": order.get("created_at"),
        "items_summary": items_summary(items),
        "distance_km": round(distance, 1) if distance is not None else None,
        "items": [{
            "product_id": i.get("product_id"), "product_name": i["product_name"],
            "size": i.get("size"), "color": i.get("color"),
            "quantity": i["quantity"], "price": i["price"],
            "image_url": images.get(i.get("product_id")),
        } for i in items],
    }


def main_image_map(image_rows):
    """Gom danh sách ảnh thành dict product_id -> ảnh chính."""
    by_product = {}
    for row in image_rows:
        by_product.setdefault(row["product_id"], []).append(row)
    return {pid: catalog.main_image(rows) for pid, rows in by_product.items()}


def check_seller_transition(current, new):
    """Kiểm tra Seller có được chuyển đơn từ current sang new không. Sai luật thì ném OrderError 422."""
    if new not in SELLER_TRANSITIONS.get(current, ()):
        raise OrderError(
            "INVALID_STATE",
            f"Không thể chuyển đơn từ \"{STATUS_LABELS.get(current, current)}\" sang \"{STATUS_LABELS.get(new, new)}\".",
            422)