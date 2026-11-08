"""Xử lý danh sách sản phẩm: dựng thẻ, lọc, sắp xếp, phân trang.

Tách riêng khỏi route để test được mà không cần kết nối Supabase.
Ở quy mô đồ án (vài trăm sản phẩm) lọc bằng Python cho đơn giản, dễ giải thích.
"""
import unicodedata

SORTS = ("newest", "price_asc", "price_desc", "popular")
DEFAULT_PAGE_SIZE = 9
MAX_PAGE_SIZE = 100


def normalize(text):
    """Chữ thường, bỏ dấu tiếng Việt để tìm kiếm không phân biệt dấu."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


def parse_int(value, default=None):
    """Đổi sang số nguyên, sai định dạng thì trả về default."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def short_text(text, limit=100):
    """Rút gọn mô tả cho thẻ sản phẩm (hiển thị 2 dòng)."""
    text = (text or "").strip()
    return text if len(text) <= limit else text[: limit - 1].rstrip() + "…"


def main_image(images):
    """Ảnh chính: ưu tiên is_main, sau đó theo position."""
    if not images:
        return None
    ordered = sorted(images, key=lambda i: (not i.get("is_main"), i.get("position", 0)))
    return ordered[0]["url"]


def rating_stats(reviews):
    """Trả về (điểm trung bình làm tròn 1 chữ số, số lượt đánh giá)."""
    ratings = [r["rating"] for r in (reviews or [])]
    if not ratings:
        return 0.0, 0
    return round(sum(ratings) / len(ratings), 1), len(ratings)


def build_card(row):
    """Dựng thẻ sản phẩm đúng hợp đồng mục 9.0."""
    avg, count = rating_stats(row.get("reviews"))
    shop = row.get("shops") or {}
    return {
        "id": row["id"],
        "name": row["name"],
        "short_description": short_text(row.get("description")),
        "price": row["price"],
        "category": row["category"],
        "image_url": main_image(row.get("product_images")),
        "shop_id": row["shop_id"],
        "shop_name": shop.get("name"),
        "rating_avg": avg,
        "rating_count": count,
        "sold_count": row.get("sold_count", 0),
    }


def build_detail(row, variants):
    """Dựng chi tiết sản phẩm: thẻ + mô tả, ảnh, biến thể, thông tin shop (mục 9.2)."""
    card = build_card(row)
    shop = row.get("shops") or {}
    images = sorted(row.get("product_images") or [], key=lambda i: (not i.get("is_main"), i.get("position", 0)))
    card.update({
        "description": row.get("description") or "",
        "tags": row.get("tags") or [],
        "suits_shapes": row.get("suits_shapes") or [],
        "images": [{"url": i["url"], "is_main": bool(i.get("is_main"))} for i in images],
        "variants": [
            {"id": v["id"], "size": v["size"], "color": v["color"], "stock": v["stock"]}
            for v in sorted(variants, key=lambda v: v["id"])
        ],
        "tryon_layer_url": row.get("tryon_layer_url"),
        "tryon_model_url": row.get("tryon_model_url"),
        "shop": {"id": row["shop_id"], "name": shop.get("name"), "owner_id": shop.get("owner_id")},
    })
    return card


def filter_rows(rows, q=None, category=None, size=None, min_price=None, max_price=None, shop_id=None):
    """Lọc theo từ khóa (tên, mô tả, tên shop), danh mục, size còn hàng, khoảng giá, shop."""
    keyword = normalize(q).strip() if q else ""
    result = []
    for row in rows:
        shop_name = (row.get("shops") or {}).get("name", "")
        if keyword and keyword not in normalize(f"{row['name']} {row.get('description') or ''} {shop_name}"):
            continue
        if category and row["category"] != category:
            continue
        if size and not any(
            v["size"].upper() == size.upper() and v["stock"] > 0
            for v in (row.get("product_variants") or [])
        ):
            continue
        if min_price is not None and row["price"] < min_price:
            continue
        if max_price is not None and row["price"] > max_price:
            continue
        if shop_id is not None and row["shop_id"] != shop_id:
            continue
        result.append(row)
    return result


def sort_rows(rows, sort="newest"):
    """Sắp xếp theo newest, price_asc, price_desc, popular. Cùng giá trị thì theo id để ổn định."""
    if sort == "price_asc":
        return sorted(rows, key=lambda r: (r["price"], r["id"]))
    if sort == "price_desc":
        return sorted(rows, key=lambda r: (-r["price"], r["id"]))
    if sort == "popular":
        return sorted(rows, key=lambda r: (-r.get("sold_count", 0), r["id"]))
    return sorted(rows, key=lambda r: (r.get("created_at") or "", r["id"]), reverse=True)


def paginate(items, page, page_size):
    """Phân trang theo định dạng mục 9.0."""
    page = max(1, page)
    page_size = min(max(1, page_size), MAX_PAGE_SIZE)
    start = (page - 1) * page_size
    return {"items": items[start:start + page_size], "page": page, "page_size": page_size, "total": len(items)}