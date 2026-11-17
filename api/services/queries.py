"""Các truy vấn dùng chung cho giỏ hàng và đơn hàng (chia nhỏ từng bảng cho dễ đọc, dễ test)."""
from . import catalog, ordering


def fetch_by_ids(db, table, ids, columns="*"):
    """Lấy các dòng theo danh sách id, trả về dict id -> dòng."""
    ids = sorted(set(ids))
    if not ids:
        return {}
    return {row["id"]: row for row in fetch_in_chunks(db, table, "id", ids, columns)}


def fetch_product_rows(db, product_ids):
    """Lấy sản phẩm kèm shop, ảnh, đánh giá theo đúng dạng catalog.build_card cần."""
    products = fetch_by_ids(
        db, "products", product_ids,
        "id,name,description,price,category,sold_count,created_at,shop_id,moderation_status,is_active")
    if not products:
        return {}
    ids = list(products)
    shops = fetch_by_ids(db, "shops", [p["shop_id"] for p in products.values()], "id,name")
    images = fetch_in_chunks(db, "product_images", "product_id", ids, "product_id,url,is_main,position")
    reviews = fetch_in_chunks(db, "reviews", "product_id", ids, "product_id,rating")
    for pid, product in products.items():
        product["shops"] = shops.get(product["shop_id"])
        product["product_images"] = [i for i in images if i["product_id"] == pid]
        product["reviews"] = [r for r in reviews if r["product_id"] == pid]
    return products


def fetch_main_images(db, product_ids):
    """Lấy ảnh chính của các sản phẩm, trả về dict product_id -> url."""
    ids = sorted({pid for pid in product_ids if pid is not None})
    if not ids:
        return {}
    rows = fetch_in_chunks(db, "product_images", "product_id", ids, "product_id,url,is_main,position")
    return ordering.main_image_map(rows)


def build_order_views(db, orders, with_buyer=False):
    """Dựng danh sách đơn kèm shop, sản phẩm, ảnh chính (mỗi bảng truy vấn một lần).

    with_buyer=True thêm buyer { name, phone } lấy từ hồ sơ người mua (dùng cho Seller).
    """
    if not orders:
        return []
    order_ids = [o["id"] for o in orders]
    item_rows = db.table("order_items").select(
        "order_id,product_id,product_name,size,color,quantity,price").in_("order_id", order_ids).execute().data
    shops = fetch_by_ids(db, "shops", [o["shop_id"] for o in orders], "id,name,lat,lng,address")
    images = fetch_main_images(db, [i["product_id"] for i in item_rows])
    buyers = fetch_by_ids(db, "profiles", [o["buyer_id"] for o in orders], "id,username,full_name,phone") if with_buyer else {}

    views = []
    for order in orders:
        view = ordering.order_view(
            order, shops.get(order["shop_id"]),
            [i for i in item_rows if i["order_id"] == order["id"]], images)
        if with_buyer:
            buyer = buyers.get(order["buyer_id"]) or {}
            view["buyer"] = {"name": buyer.get("full_name") or buyer.get("username"), "phone": buyer.get("phone")}
            view["platform_fee_rate"] = order.get("platform_fee_rate", 0)
            view["platform_fee"] = order.get("platform_fee", 0)
            view["seller_net"] = order.get("seller_net", 0)
        views.append(view)
    return views


def shop_of_owner(db, owner_id):
    """Shop của một Seller (mỗi Seller đúng một shop), hoặc None."""
    rows = db.table("shops").select("*").eq("owner_id", owner_id).limit(1).execute().data
    return rows[0] if rows else None


PAGE_SIZE = 1000   # Supabase chỉ trả tối đa 1000 dòng mỗi lần gọi, nhiều hơn thì bị cắt âm thầm


def fetch_all(build, limit=50000):
    """Lấy mọi dòng của một truy vấn bằng cách đọc từng trang 1000 dòng.

    build: hàm không tham số, mỗi lần gọi trả về một truy vấn MỚI (nên có order để thứ tự ổn định giữa các trang).
    """
    rows, start = [], 0
    while True:
        chunk = build().range(start, start + PAGE_SIZE - 1).execute().data
        rows.extend(chunk)
        if len(chunk) < PAGE_SIZE or len(rows) >= limit:
            return rows
        start += PAGE_SIZE


def fetch_in_chunks(db, table, column, values, columns="*", size=150):
    """Lấy các dòng có `column` nằm trong danh sách `values`, chia nhỏ để địa chỉ truy vấn không quá dài."""
    values = sorted(set(values))
    rows = []
    for i in range(0, len(values), size):
        rows += db.table(table).select(columns).in_(column, values[i:i + size]).execute().data
    return rows