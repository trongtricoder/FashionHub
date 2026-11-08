"""Lấy dữ liệu sản phẩm đang bán cho gợi ý và chatbot của Buyer (mục 10.2, 10.6)."""
from .queries import fetch_all, fetch_by_ids, fetch_in_chunks


def visible_products(db, columns):
    """Sản phẩm đã duyệt, đang bán, thuộc shop đã duyệt."""
    products = fetch_all(lambda: (
        db.table("products").select(columns).eq("moderation_status", "approved").eq("is_active", True).order("id")))
    shops = fetch_by_ids(db, "shops", [p["shop_id"] for p in products], "id,moderation_status")
    return [p for p in products if (shops.get(p["shop_id"]) or {}).get("moderation_status") == "approved"]


def load_candidates(db):
    """Ứng viên gợi ý: sản phẩm đang bán và còn ít nhất một biến thể còn hàng, kèm size còn hàng, điểm đánh giá."""
    products = visible_products(db, "id,shop_id,name,price,tags,suits_shapes,sold_count")
    ids = [p["id"] for p in products]
    variants = fetch_in_chunks(db, "product_variants", "product_id", ids, "product_id,size,stock")
    reviews = fetch_in_chunks(db, "reviews", "product_id", ids, "product_id,rating")

    sizes, ratings = {}, {}
    for v in variants:
        if v["stock"] > 0:
            sizes.setdefault(v["product_id"], set()).add(v["size"])
    for r in reviews:
        ratings.setdefault(r["product_id"], []).append(r["rating"])

    candidates = []
    for p in products:
        if p["id"] not in sizes:   # hết hàng toàn bộ thì không gợi ý
            continue
        given = ratings.get(p["id"], [])
        candidates.append({
            "id": p["id"], "shop_id": p["shop_id"], "name": p["name"], "price": p["price"],
            "tags": p.get("tags") or [], "suits_shapes": p.get("suits_shapes") or [],
            "sold_count": p.get("sold_count") or 0, "sizes": sizes[p["id"]],
            "rating_avg": sum(given) / len(given) if given else 0, "rating_count": len(given),
        })
    return candidates


def chatbot_products(db):
    """Danh sách sản phẩm đang bán để chatbot tìm theo tên, tag, danh mục."""
    return visible_products(db, "id,shop_id,name,tags,category,sold_count")