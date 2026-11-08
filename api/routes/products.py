"""Danh sách và chi tiết sản phẩm công khai (mục 9.2). Chỉ trả sản phẩm approved và is_active."""
from flask import Blueprint, g, request

from ..services import catalog
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import fetch_all, fetch_by_ids
from ..services.responses import fail, ok

bp = Blueprint("products", __name__, url_prefix="/api/products")

# Kéo kèm shop, ảnh, biến thể, đánh giá trong một truy vấn (quan hệ khóa ngoại của PostgREST)
LIST_SELECT = (
    "id,name,description,price,category,sold_count,created_at,shop_id,"
    "shops(name,moderation_status),product_images(url,is_main,position),"
    "product_variants(size,stock),reviews(rating)"
)
DETAIL_SELECT = (
    "id,name,description,price,category,sold_count,created_at,shop_id,tags,suits_shapes,"
    "tryon_layer_url,tryon_model_url,"
    "shops(id,name,owner_id,moderation_status),product_images(url,is_main,position),reviews(rating)"
)


def _shop_visible(row):
    """Shop bị Detector giữ lại (pending, blocked, rejected) thì sản phẩm của shop không hiện công khai."""
    return (row.get("shops") or {}).get("moderation_status", "approved") == "approved"


@bp.get("")
def list_products():
    """GET /api/products?q&category&size&min_price&max_price&shop_id&sort&page&page_size."""
    args = request.args
    sort = args.get("sort", "newest")
    if sort not in catalog.SORTS:
        return fail("INVALID_INPUT", "Giá trị sort không hợp lệ.", 400)
    category = args.get("category")
    if category and category not in ("ao", "quan", "vay-dam", "phu-kien"):
        return fail("INVALID_INPUT", "Danh mục không hợp lệ.", 400)

    rows = (
        get_db().table("products").select(LIST_SELECT)
        .eq("moderation_status", "approved").eq("is_active", True)
        .execute().data
    )
    rows = [r for r in rows if _shop_visible(r)]
    rows = catalog.filter_rows(
        rows,
        q=args.get("q"),
        category=category,
        size=args.get("size"),
        min_price=catalog.parse_int(args.get("min_price")),
        max_price=catalog.parse_int(args.get("max_price")),
        shop_id=catalog.parse_int(args.get("shop_id")),
    )
    rows = catalog.sort_rows(rows, sort)
    page = catalog.paginate(
        rows,
        catalog.parse_int(args.get("page"), 1),
        catalog.parse_int(args.get("page_size"), catalog.DEFAULT_PAGE_SIZE),
    )
    page["items"] = [catalog.build_card(r) for r in page["items"]]
    return ok(page)


@bp.get("/<int:product_id>")
def product_detail(product_id):
    """GET /api/products/{id}: chi tiết kèm biến thể (size, màu, tồn kho)."""
    db = get_db()
    rows = (
        db.table("products").select(DETAIL_SELECT).eq("id", product_id)
        .eq("moderation_status", "approved").eq("is_active", True)
        .limit(1).execute().data
    )
    if not rows or not _shop_visible(rows[0]):
        return fail("NOT_FOUND", "Không tìm thấy sản phẩm.", 404)
    variants = db.table("product_variants").select("id,size,color,stock").eq("product_id", product_id).execute().data
    return ok(catalog.build_detail(rows[0], variants))


# ---------- Đánh giá ----------

MAX_COMMENT = 500
REVIEW_PAGE_SIZE = 10


def _visible_product(db, product_id):
    """Sản phẩm đang được bán công khai (đã duyệt, đang hiển thị, shop đã duyệt), hoặc None."""
    rows = (db.table("products").select("id,shop_id").eq("id", product_id)
            .eq("moderation_status", "approved").eq("is_active", True).limit(1).execute().data)
    if not rows:
        return None
    shop = fetch_by_ids(db, "shops", [rows[0]["shop_id"]], "id,moderation_status").get(rows[0]["shop_id"]) or {}
    return rows[0] if shop.get("moderation_status") == "approved" else None


@bp.get("/<int:product_id>/reviews")
def list_reviews(product_id):
    """GET /api/products/{id}/reviews?page: đánh giá mới nhất trước, kèm điểm trung bình và tổng số lượt."""
    db = get_db()
    if not _visible_product(db, product_id):
        return fail("NOT_FOUND", "Không tìm thấy sản phẩm.", 404)
    rows = fetch_all(lambda: db.table("reviews").select("*").eq("product_id", product_id).order("id", desc=True))
    users = fetch_by_ids(db, "profiles", [r["user_id"] for r in rows], "id,username,full_name")
    page = catalog.paginate(rows, catalog.parse_int(request.args.get("page"), 1), REVIEW_PAGE_SIZE)
    page["items"] = [{
        "id": r["id"], "rating": r["rating"], "comment": r.get("comment") or "", "created_at": r.get("created_at"),
        "user_name": (users.get(r["user_id"]) or {}).get("full_name") or (users.get(r["user_id"]) or {}).get("username") or "Người mua",
    } for r in page["items"]]
    avg, count = catalog.rating_stats(rows)
    page.update({"rating_avg": avg, "rating_count": count})
    return ok(page)


@bp.post("/<int:product_id>/reviews")
@require_role("buyer")
def post_review(product_id):
    """POST /api/products/{id}/reviews { rating, comment }: mỗi người mua một đánh giá cho mỗi sản phẩm, gửi lại sẽ cập nhật."""
    body = request.get_json(silent=True) or {}
    rating = body.get("rating")
    if isinstance(rating, bool) or not isinstance(rating, int) or not 1 <= rating <= 5:
        return fail("INVALID_INPUT", "Số sao phải từ 1 đến 5.", 400)
    comment = str(body.get("comment") or "").strip()
    if len(comment) > MAX_COMMENT:
        return fail("INVALID_INPUT", f"Nhận xét tối đa {MAX_COMMENT} ký tự.", 400)

    db = get_db()
    if not _visible_product(db, product_id):
        return fail("NOT_FOUND", "Không tìm thấy sản phẩm.", 404)
    existing = db.table("reviews").select("id").eq("product_id", product_id).eq("user_id", g.user["id"]).limit(1).execute().data
    if existing:
        row = db.table("reviews").update({"rating": rating, "comment": comment}).eq("id", existing[0]["id"]).execute().data[0]
        return ok(row)
    row = db.table("reviews").insert({"product_id": product_id, "user_id": g.user["id"], "rating": rating, "comment": comment}).execute().data[0]
    return ok(row, 201)