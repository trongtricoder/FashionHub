"""Seller quản lý shop và sản phẩm (mục 9.5): sửa shop, thêm, sửa, xóa sản phẩm, tải ảnh.

Mọi thay đổi đều đi qua AI Detector (mục 10.3) trước khi được hiển thị cho người mua.
"""
import uuid

from flask import Blueprint, current_app, g, request

from ai.detector import detect

from ..services import catalog, moderation, product_input, uploads
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import fetch_by_ids, shop_of_owner
from ..services.responses import fail, ok

bp = Blueprint("seller_catalog", __name__, url_prefix="/api/seller")

STORAGE_BUCKET = "product-images"
STATUSES = ("approved", "pending", "blocked", "rejected")


def _shop(db):
    return shop_of_owner(db, g.user["id"])


def _no_shop():
    return fail("SHOP_NOT_FOUND", "Tài khoản của bạn chưa có shop.", 404)


def _moderation_payload(result, account):
    """Kết quả kiểm duyệt trả cho giao diện: quyết định, điểm, lý do, và xử lý tài khoản nếu có."""
    return {"decision": result["decision"], "risk_score": result["risk_score"],
            "reasons": result["reasons"], "account": account}


def _shop_view(shop):
    return {k: shop.get(k) for k in (
        "id", "name", "description", "address", "lat", "lng", "prep_minutes", "moderation_status")}


# ---------- Shop ----------

@bp.put("/shop")
@require_role("seller")
def update_shop():
    """PUT /api/seller/shop: sửa thông tin shop, chạy AI Detector cho shop."""
    db = get_db()
    shop = _shop(db)
    if not shop:
        return _no_shop()
    try:
        clean = product_input.parse_shop(request.get_json(silent=True) or {})
    except product_input.InputError as err:
        return fail("INVALID_INPUT", str(err), 400)

    result = detect.score("shop", clean)
    clean["moderation_status"] = result["decision"]
    updated = db.table("shops").update(clean).eq("id", shop["id"]).execute().data[0]
    account = moderation.apply_decision(db, "shop", shop["id"], g.user["id"], result)
    return ok({"shop": _shop_view(updated), "moderation": _moderation_payload(result, account)})


# ---------- Sản phẩm ----------

def _own_product(db, shop, product_id):
    rows = db.table("products").select("*").eq("id", product_id).eq("shop_id", shop["id"]).limit(1).execute().data
    return rows[0] if rows else None


def _product_detail(db, product):
    """Chi tiết đầy đủ của một sản phẩm cho form sửa: kèm phân loại và ảnh."""
    variants = db.table("product_variants").select("id,size,color,stock").eq("product_id", product["id"]).order("id").execute().data
    images = db.table("product_images").select("url,is_main,position").eq("product_id", product["id"]).order("position").execute().data
    return {
        "id": product["id"], "name": product["name"], "description": product.get("description") or "",
        "price": product["price"], "category": product["category"], "tags": product.get("tags") or [],
        "suits_shapes": product.get("suits_shapes") or [], "tryon_layer_url": product.get("tryon_layer_url"),
        "moderation_status": product["moderation_status"], "risk_score": product.get("risk_score", 0),
        "risk_reasons": product.get("risk_reasons") or [], "sold_count": product.get("sold_count", 0),
        "is_active": product.get("is_active", True),
        "variants": variants,
        "images": [{"url": i["url"], "is_main": bool(i["is_main"])} for i in images],
    }


@bp.get("/products")
@require_role("seller")
def list_products():
    """GET /api/seller/products?status=: sản phẩm của shop kèm trạng thái duyệt, lý do, tổng tồn kho."""
    status = request.args.get("status")
    if status and status not in STATUSES:
        return fail("INVALID_INPUT", "Trạng thái không hợp lệ.", 400)
    db = get_db()
    shop = _shop(db)
    if not shop:
        return _no_shop()

    query = db.table("products").select("*").eq("shop_id", shop["id"]).eq("is_active", True)
    if status:
        query = query.eq("moderation_status", status)
    products = query.order("id", desc=True).execute().data

    ids = [p["id"] for p in products]
    variants = db.table("product_variants").select("product_id,stock").in_("product_id", ids).execute().data if ids else []
    images = db.table("product_images").select("product_id,url,is_main,position").in_("product_id", ids).execute().data if ids else []
    items = []
    for p in products:
        items.append({
            "id": p["id"], "name": p["name"], "price": p["price"], "category": p["category"],
            "image_url": catalog.main_image([i for i in images if i["product_id"] == p["id"]]),
            "moderation_status": p["moderation_status"], "risk_score": p.get("risk_score", 0),
            "risk_reasons": p.get("risk_reasons") or [],
            "stock_total": sum(v["stock"] for v in variants if v["product_id"] == p["id"]),
            "sold_count": p.get("sold_count", 0),
        })
    return ok({"items": items})


@bp.get("/products/<int:product_id>")
@require_role("seller")
def get_product(product_id):
    """GET /api/seller/products/{id}: dữ liệu đầy đủ để đổ vào form sửa."""
    db = get_db()
    shop = _shop(db)
    if not shop:
        return _no_shop()
    product = _own_product(db, shop, product_id)
    if not product:
        return fail("NOT_FOUND", "Không tìm thấy sản phẩm.", 404)
    return ok(_product_detail(db, product))


def _insert_children(db, product_id, clean):
    """Thêm biến thể và ảnh của một sản phẩm mới."""
    db.table("product_variants").insert([dict(v, product_id=product_id) for v in clean["variants"]]).execute()
    if clean["images"]:
        db.table("product_images").insert([
            {"product_id": product_id, "url": img["url"], "is_main": img["is_main"], "position": pos}
            for pos, img in enumerate(clean["images"])
        ]).execute()


def _evaluate(db, shop, clean):
    """Chạy AI Detector cho một sản phẩm."""
    return detect.score("product", {
        "name": clean["name"], "description": clean["description"], "price": clean["price"],
        "image_count": len(clean["images"]),
        "duplicate_names": moderation.other_shop_product_names(db, shop["id"]),
    })


def _product_fields(clean, result):
    return {
        "name": clean["name"], "description": clean["description"], "price": clean["price"],
        "category": clean["category"], "tags": clean["tags"], "suits_shapes": clean["suits_shapes"],
        "tryon_layer_url": clean["tryon_layer_url"],
        "moderation_status": result["decision"], "risk_score": result["risk_score"],
        "risk_reasons": result["reasons"],
    }


@bp.post("/products")
@require_role("seller")
def create_product():
    """POST /api/seller/products: tạo sản phẩm, chạy AI Detector, trả về kết quả kiểm duyệt."""
    db = get_db()
    shop = _shop(db)
    if not shop:
        return _no_shop()
    try:
        clean = product_input.parse_product(request.get_json(silent=True) or {})
    except product_input.InputError as err:
        return fail("INVALID_INPUT", str(err), 400)

    result = _evaluate(db, shop, clean)
    product = None
    try:
        product = db.table("products").insert(dict(_product_fields(clean, result), shop_id=shop["id"])).execute().data[0]
        _insert_children(db, product["id"], clean)
    except Exception:
        current_app.logger.exception("Tạo sản phẩm thất bại, xóa phần đã tạo")
        if product:
            db.table("products").delete().eq("id", product["id"]).execute()  # biến thể, ảnh xóa theo (cascade)
        return fail("SAVE_FAILED", "Không lưu được sản phẩm, vui lòng thử lại.", 500)

    account = moderation.apply_decision(db, "product", product["id"], g.user["id"], result)
    return ok({"product": _product_detail(db, product), "moderation": _moderation_payload(result, account)}, 201)


def _sync_variants(db, product_id, new_variants):
    """Cập nhật phân loại giữ nguyên id cũ (để giỏ hàng và đơn hàng cũ không mất liên kết).

    Phân loại bị bỏ đi mà đã có trong đơn hàng thì không xóa được (ném InputError).
    """
    existing = db.table("product_variants").select("id,size,color,stock").eq("product_id", product_id).execute().data
    by_key = {(v["size"].lower(), v["color"].lower()): v for v in existing}
    wanted = {(v["size"].lower(), v["color"].lower()) for v in new_variants}

    removed = [v for key, v in by_key.items() if key not in wanted]
    if removed:
        used = db.table("order_items").select("variant_id").in_("variant_id", [v["id"] for v in removed]).execute().data
        used_ids = {row["variant_id"] for row in used}
        blocked = [f"{v['size']} / {v['color']}" for v in removed if v["id"] in used_ids]
        if blocked:
            raise product_input.InputError(
                "Phân loại đã có trong đơn hàng nên không xóa được: " + ", ".join(blocked)
                + ". Hãy đặt tồn kho về 0 thay vì xóa.")
        db.table("product_variants").delete().in_("id", [v["id"] for v in removed]).execute()

    for variant in new_variants:
        key = (variant["size"].lower(), variant["color"].lower())
        if key in by_key:
            db.table("product_variants").update(
                {"size": variant["size"], "color": variant["color"], "stock": variant["stock"]}
            ).eq("id", by_key[key]["id"]).execute()
        else:
            db.table("product_variants").insert(dict(variant, product_id=product_id)).execute()


@bp.put("/products/<int:product_id>")
@require_role("seller")
def update_product(product_id):
    """PUT /api/seller/products/{id}: sửa sản phẩm và kiểm duyệt lại."""
    db = get_db()
    shop = _shop(db)
    if not shop:
        return _no_shop()
    existing = _own_product(db, shop, product_id)
    if not existing:
        return fail("NOT_FOUND", "Không tìm thấy sản phẩm.", 404)
    try:
        clean = product_input.parse_product(request.get_json(silent=True) or {})
        _sync_variants(db, product_id, clean["variants"])
    except product_input.InputError as err:
        return fail("INVALID_INPUT", str(err), 400)

    result = _evaluate(db, shop, clean)
    updated = db.table("products").update(_product_fields(clean, result)).eq("id", product_id).execute().data[0]
    db.table("product_images").delete().eq("product_id", product_id).execute()
    if clean["images"]:
        db.table("product_images").insert([
            {"product_id": product_id, "url": img["url"], "is_main": img["is_main"], "position": pos}
            for pos, img in enumerate(clean["images"])
        ]).execute()

    account = moderation.apply_decision(db, "product", product_id, g.user["id"], result)
    return ok({"product": _product_detail(db, updated), "moderation": _moderation_payload(result, account)})


@bp.delete("/products/<int:product_id>")
@require_role("seller")
def delete_product(product_id):
    """DELETE /api/seller/products/{id}: đã có đơn hàng thì chỉ ẩn (is_active = false), chưa có thì xóa hẳn."""
    db = get_db()
    shop = _shop(db)
    if not shop:
        return _no_shop()
    if not _own_product(db, shop, product_id):
        return fail("NOT_FOUND", "Không tìm thấy sản phẩm.", 404)

    has_orders = db.table("order_items").select("id").eq("product_id", product_id).limit(1).execute().data
    if has_orders:
        db.table("products").update({"is_active": False}).eq("id", product_id).execute()
    else:
        db.table("products").delete().eq("id", product_id).execute()
    db.table("moderation_queue").delete().eq("target_type", "product").eq("target_id", product_id).eq("status", "pending").execute()
    return ok({"hidden": bool(has_orders)})


# ---------- Tải ảnh ----------

@bp.post("/uploads")
@require_role("seller")
def upload_image():
    """POST /api/seller/uploads (multipart, trường 'file'): kiểm tra ảnh rồi lưu vào Supabase Storage."""
    file = request.files.get("file")
    if not file:
        return fail("INVALID_INPUT", "Vui lòng chọn một ảnh.", 400)
    data = file.read(uploads.MAX_UPLOAD_BYTES + 1)
    if len(data) > uploads.MAX_UPLOAD_BYTES:
        return fail("FILE_TOO_LARGE", "Ảnh quá lớn, tối đa 5 MB.", 413)
    kind = uploads.sniff_image(data)
    if not kind:
        return fail("INVALID_INPUT", "Chỉ nhận ảnh JPG, PNG hoặc WEBP.", 400)

    db = get_db()
    shop = _shop(db)
    if not shop:
        return _no_shop()
    extension, content_type = kind
    path = f"{shop['id']}/{uuid.uuid4().hex}.{extension}"
    try:
        db.storage.from_(STORAGE_BUCKET).upload(path, data, {"content-type": content_type})
        url = db.storage.from_(STORAGE_BUCKET).get_public_url(path).rstrip("?")
    except Exception:
        current_app.logger.exception("Tải ảnh lên Supabase Storage thất bại")
        return fail("UPLOAD_FAILED", "Không tải được ảnh lên, vui lòng thử lại.", 502)
    return ok({"url": url}, 201)