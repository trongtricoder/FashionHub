"""API cho Admin (mục 9.7): quản lý tài khoản, hàng đợi duyệt, nhật ký AI chặn."""
import uuid
from datetime import date, datetime, timedelta, timezone

from flask import Blueprint, current_app, g, request

from ..services import catalog, passwords
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import fetch_all, fetch_by_ids, fetch_main_images, shop_of_owner
from ..services.responses import fail, ok

bp = Blueprint("admin", __name__, url_prefix="/api/admin")

VN_TZ = timezone(timedelta(hours=7))   # "hôm nay" tính theo giờ Việt Nam (mục 1)
ROLES = ("buyer", "seller", "admin")
QUEUE_STATUSES = ("pending", "approved", "rejected")
DEFAULT_PAGE_SIZE = 20
MAX_REASON = 300


def _now_iso():
    return datetime.now(timezone.utc).isoformat()


def _page_args():
    page = catalog.parse_int(request.args.get("page"), 1)
    size = catalog.parse_int(request.args.get("page_size"), DEFAULT_PAGE_SIZE)
    return page, size


# ======================================================================
# Tài khoản
# ======================================================================

def _valid_uuid(value):
    try:
        uuid.UUID(value)
        return True
    except (ValueError, AttributeError):
        return False


def _target_user(db, user_id):
    """Tìm tài khoản để thao tác. Trả về (profile, None) hoặc (None, response lỗi).

    Không cho thao tác trên tài khoản Admin (tránh tự khóa hoặc xóa quyền quản trị).
    """
    if not _valid_uuid(user_id):
        return None, fail("NOT_FOUND", "Không tìm thấy tài khoản.", 404)
    rows = db.table("profiles").select("*").eq("id", user_id).limit(1).execute().data
    if not rows:
        return None, fail("NOT_FOUND", "Không tìm thấy tài khoản.", 404)
    if rows[0]["role"] == "admin":
        return None, fail("FORBIDDEN", "Không thể thao tác trên tài khoản Admin.", 403)
    return rows[0], None


def _user_view(p):
    """Chỉ trả các trường an toàn. Không bao giờ trả mật khẩu (mục 9.7)."""
    return {k: p.get(k) for k in ("id", "username", "email", "role", "status", "created_at")}


@bp.get("/users")
@require_role("admin")
def list_users():
    """GET /api/admin/users?role&status&q&page&page_size."""
    role, status, q = request.args.get("role"), request.args.get("status"), request.args.get("q")
    if role and role not in ROLES:
        return fail("INVALID_INPUT", "Vai trò không hợp lệ.", 400)
    if status and status not in ("active", "banned"):
        return fail("INVALID_INPUT", "Trạng thái không hợp lệ.", 400)

    query = get_db().table("profiles").select("id,username,email,full_name,role,status,created_at")
    if role:
        query = query.eq("role", role)
    if status:
        query = query.eq("status", status)
    rows = query.order("created_at", desc=True).execute().data
    if q:
        keyword = catalog.normalize(q).strip()
        rows = [r for r in rows if keyword in catalog.normalize(
            f"{r['id']} {r['username']} {r['email']} {r.get('full_name') or ''}")]
    page, size = _page_args()
    result = catalog.paginate(rows, page, size)
    result["items"] = [_user_view(r) for r in result["items"]]
    return ok(result)


@bp.post("/users/<user_id>/reset-password")
@require_role("admin")
def reset_password(user_id):
    """POST /api/admin/users/{id}/reset-password: đặt mật khẩu tạm, bắt đổi ở lần đăng nhập sau. Chỉ trả đúng một lần."""
    db = get_db()
    target, error = _target_user(db, user_id)
    if error:
        return error
    temp = passwords.generate_temp_password()
    try:
        db.auth.admin.update_user_by_id(target["id"], {"password": temp})
    except Exception:
        current_app.logger.exception("Đặt lại mật khẩu thất bại")
        return fail("RESET_FAILED", "Không đặt lại được mật khẩu, vui lòng thử lại.", 502)
    db.table("profiles").update({"must_change_password": True}).eq("id", target["id"]).execute()
    return ok({"temp_password": temp})


@bp.post("/users/<user_id>/status")
@require_role("admin")
def set_status(user_id):
    """POST /api/admin/users/{id}/status { status: active | banned, reason? }."""
    body = request.get_json(silent=True) or {}
    status = body.get("status")
    if status not in ("active", "banned"):
        return fail("INVALID_INPUT", "Trạng thái chỉ có thể là active hoặc banned.", 400)
    db = get_db()
    target, error = _target_user(db, user_id)
    if error:
        return error
    updated = db.table("profiles").update({"status": status}).eq("id", target["id"]).execute().data[0]
    return ok(_user_view(updated))


@bp.delete("/users/<user_id>")
@require_role("admin")
def delete_user(user_id):
    """DELETE /api/admin/users/{id}: tài khoản đã có đơn hàng thì chặn và gợi ý dùng chức năng khóa."""
    db = get_db()
    target, error = _target_user(db, user_id)
    if error:
        return error

    has_orders = bool(db.table("orders").select("id").eq("buyer_id", target["id"]).limit(1).execute().data)
    shop = shop_of_owner(db, target["id"])
    if shop and not has_orders:
        has_orders = bool(db.table("orders").select("id").eq("shop_id", shop["id"]).limit(1).execute().data)
    if has_orders:
        return fail("HAS_ORDERS", "Tài khoản đã có đơn hàng nên không thể xóa. Hãy dùng chức năng Khóa.", 409)

    try:
        db.auth.admin.delete_user(target["id"])   # hồ sơ, shop, sản phẩm xóa theo (on delete cascade)
    except Exception:
        current_app.logger.exception("Xóa tài khoản thất bại")
        return fail("DELETE_FAILED", "Không xóa được tài khoản, vui lòng thử lại.", 502)
    return ok({})


# ======================================================================
# Quản lý tất cả sản phẩm
# ======================================================================

@bp.get("/products")
@require_role("admin")
def list_products():
    """GET /api/admin/products?status&q&page&page_size: liệt kê cả sản phẩm chưa duyệt và đã duyệt."""
    status = request.args.get("status", "all")
    if status not in ("all", "pending", "approved", "blocked", "rejected"):
        return fail("INVALID_INPUT", "Trạng thái sản phẩm không hợp lệ.", 400)

    db = get_db()
    rows = fetch_all(lambda: (
        db.table("products").select(
            "id,name,description,price,category,shop_id,moderation_status,is_active,created_at"
        ).order("created_at", desc=True)
    ))
    if status != "all":
        rows = [row for row in rows if row["moderation_status"] == status]
    keyword = catalog.normalize(request.args.get("q") or "").strip()
    if keyword:
        rows = [row for row in rows if keyword in catalog.normalize(
            f"{row['name']} {row.get('description') or ''}")]

    page, size = _page_args()
    result = catalog.paginate(rows, page, size)
    page_rows = result["items"]
    shops = fetch_by_ids(db, "shops", [row["shop_id"] for row in page_rows], "id,name")
    images = fetch_main_images(db, [row["id"] for row in page_rows])
    result["items"] = [{
        "id": row["id"],
        "name": row["name"],
        "description": row.get("description") or "",
        "price": row["price"],
        "category": row["category"],
        "moderation_status": row["moderation_status"],
        "is_active": bool(row.get("is_active", True)),
        "created_at": row.get("created_at"),
        "shop_name": (shops.get(row["shop_id"]) or {}).get("name") or "",
        "image_url": images.get(row["id"]),
    } for row in page_rows]
    return ok(result)


@bp.post("/products/<int:product_id>/block")
@require_role("admin")
def block_product(product_id):
    """POST /api/admin/products/{id}/block: chặn sản phẩm đã duyệt mà không xóa dữ liệu."""
    db = get_db()
    rows = db.table("products").select(
        "id,moderation_status"
    ).eq("id", product_id).limit(1).execute().data
    if not rows:
        return fail("NOT_FOUND", "Không tìm thấy sản phẩm.", 404)
    if rows[0]["moderation_status"] != "approved":
        return fail("INVALID_STATE", "Chỉ có thể khóa sản phẩm đã duyệt.", 422)

    updated = (db.table("products").update({"moderation_status": "blocked"})
               .eq("id", product_id).eq("moderation_status", "approved").execute().data)
    if not updated:
        return fail("CONFLICT", "Sản phẩm vừa được cập nhật, vui lòng tải lại.", 409)
    return ok({"id": product_id, "moderation_status": "blocked"})


# ======================================================================
# Hàng đợi duyệt
# ======================================================================

def _queue_context(db, queue_rows):
    """Gom tên đối tượng, chủ sở hữu, thông tin chi tiết cho các mục hàng đợi (mỗi bảng truy vấn một lần)."""
    product_ids = [r["target_id"] for r in queue_rows if r["target_type"] == "product"]
    shop_ids = [r["target_id"] for r in queue_rows if r["target_type"] == "shop"]
    products = fetch_by_ids(db, "products", product_ids)
    shops = fetch_by_ids(db, "shops", shop_ids + [p["shop_id"] for p in products.values()])
    owners = fetch_by_ids(db, "profiles", [s["owner_id"] for s in shops.values()], "id,username,full_name")
    return products, shops, owners


def _owner_name(owner):
    return (owner or {}).get("full_name") or (owner or {}).get("username")


def _queue_item(row, products, shops, owners):
    if row["target_type"] == "product":
        product = products.get(row["target_id"]) or {}
        shop = shops.get(product.get("shop_id")) or {}
        name = product.get("name")
    else:
        shop = shops.get(row["target_id"]) or {}
        name = shop.get("name")
    return {
        "id": row["id"], "target_type": row["target_type"], "target_id": row["target_id"],
        "name": name or "(đã bị xóa)", "owner_name": _owner_name(owners.get(shop.get("owner_id"))),
        "risk_score": row["risk_score"], "reasons": row.get("reasons") or [],
        "status": row["status"], "reject_reason": row.get("reject_reason"), "created_at": row.get("created_at"),
    }


@bp.get("/moderation")
@require_role("admin")
def list_moderation():
    """GET /api/admin/moderation?status=pending|approved|rejected&page."""
    status = request.args.get("status", "pending")
    if status not in QUEUE_STATUSES:
        return fail("INVALID_INPUT", "Trạng thái không hợp lệ.", 400)
    db = get_db()
    rows = db.table("moderation_queue").select("*").eq("status", status).order("created_at", desc=True).execute().data
    page, size = _page_args()
    result = catalog.paginate(rows, page, size)
    products, shops, owners = _queue_context(db, result["items"])
    result["items"] = [_queue_item(r, products, shops, owners) for r in result["items"]]
    return ok(result)


def _queue_row(db, item_id):
    rows = db.table("moderation_queue").select("*").eq("id", item_id).limit(1).execute().data
    return rows[0] if rows else None


@bp.get("/moderation/<int:item_id>")
@require_role("admin")
def moderation_detail(item_id):
    """GET /api/admin/moderation/{id}: chi tiết để Admin xem trước khi quyết định."""
    db = get_db()
    row = _queue_row(db, item_id)
    if not row:
        return fail("NOT_FOUND", "Không tìm thấy mục kiểm duyệt.", 404)
    products, shops, owners = _queue_context(db, [row])
    item = _queue_item(row, products, shops, owners)

    if row["target_type"] == "product":
        product = products.get(row["target_id"]) or {}
        images = db.table("product_images").select("url,is_main,position").eq("product_id", row["target_id"]).order("position").execute().data
        item.update({
            "description": product.get("description") or "", "price": product.get("price"),
            "category": product.get("category"), "tags": product.get("tags") or [],
            "images": [{"url": i["url"], "is_main": bool(i["is_main"])} for i in images],
            "current_status": product.get("moderation_status"),
            "shop_name": (shops.get(product.get("shop_id")) or {}).get("name"),
        })
    else:
        shop = shops.get(row["target_id"]) or {}
        item.update({"description": shop.get("description") or "", "address": shop.get("address") or "",
                     "current_status": shop.get("moderation_status"), "price": None, "images": [], "tags": []})
    return ok(item)


def _set_target_status(db, row, status, extra=None):
    """Đổi moderation_status của sản phẩm hoặc shop theo quyết định của Admin."""
    table = "products" if row["target_type"] == "product" else "shops"
    fields = dict(extra or {}, moderation_status=status)
    db.table(table).update(fields).eq("id", row["target_id"]).execute()


def _close_item(db, row, status, reason=None):
    db.table("moderation_queue").update({
        "status": status, "reject_reason": reason,
        "reviewed_by": g.user["id"], "reviewed_at": _now_iso(),
    }).eq("id", row["id"]).execute()


def _pending_or_error(db, item_id):
    row = _queue_row(db, item_id)
    if not row:
        return None, fail("NOT_FOUND", "Không tìm thấy mục kiểm duyệt.", 404)
    if row["status"] != "pending":
        return None, fail("INVALID_STATE", "Mục này đã được xử lý rồi.", 422)
    return row, None


@bp.post("/moderation/<int:item_id>/approve")
@require_role("admin")
def approve(item_id):
    """POST /api/admin/moderation/{id}/approve: duyệt, đối tượng hiển thị với người mua."""
    db = get_db()
    row, error = _pending_or_error(db, item_id)
    if error:
        return error
    _set_target_status(db, row, "approved")
    _close_item(db, row, "approved")
    # Các dòng nhật ký của đối tượng này được tính là đã khôi phục
    db.table("ai_block_logs").update({"restored": True}).eq("target_type", row["target_type"]).eq("target_id", str(row["target_id"])).eq("restored", False).execute()
    return ok({})


@bp.post("/moderation/<int:item_id>/reject")
@require_role("admin")
def reject(item_id):
    """POST /api/admin/moderation/{id}/reject { reason }: từ chối, lý do hiện cho Seller ở trang sửa."""
    body = request.get_json(silent=True) or {}
    reason = str(body.get("reason") or "").strip()
    if not reason:
        return fail("INVALID_INPUT", "Vui lòng nhập lý do từ chối.", 400)
    if len(reason) > MAX_REASON:
        return fail("INVALID_INPUT", f"Lý do tối đa {MAX_REASON} ký tự.", 400)

    db = get_db()
    row, error = _pending_or_error(db, item_id)
    if error:
        return error
    extra = None
    if row["target_type"] == "product":
        # Đưa lý do của Admin lên đầu danh sách lý do để Seller đọc thấy ngay ở trang sửa sản phẩm
        current = db.table("products").select("risk_reasons").eq("id", row["target_id"]).limit(1).execute().data
        old = (current[0].get("risk_reasons") if current else None) or []
        extra = {"risk_reasons": [{"rule": "admin_rejected", "points": 0, "detail": f"Admin từ chối: {reason}"}] + old}
    _set_target_status(db, row, "rejected", extra)
    _close_item(db, row, "rejected", reason)
    return ok({})


# ======================================================================
# AI chặn hôm nay
# ======================================================================

def _day_range(date_text):
    """Khoảng thời gian của một ngày theo giờ Việt Nam, đổi sang UTC. Trả về (đầu, cuối) hoặc None nếu sai định dạng."""
    if date_text in (None, "", "today"):
        day = datetime.now(VN_TZ).date()
    else:
        try:
            day = date.fromisoformat(date_text)
        except ValueError:
            return None
    start = datetime(day.year, day.month, day.day, tzinfo=VN_TZ)
    return start.astimezone(timezone.utc), (start + timedelta(days=1)).astimezone(timezone.utc)


@bp.get("/ai-blocked")
@require_role("admin")
def ai_blocked():
    """GET /api/admin/ai-blocked?date=today|YYYY-MM-DD: nhật ký của AI Detector trong ngày kèm 3 số liệu."""
    day = _day_range(request.args.get("date"))
    if not day:
        return fail("INVALID_INPUT", "Ngày phải có dạng YYYY-MM-DD hoặc today.", 400)
    start, end = day

    db = get_db()
    logs = (db.table("ai_block_logs").select("*")
            .gte("created_at", start.isoformat()).lt("created_at", end.isoformat())
            .order("created_at", desc=True).execute().data)

    product_ids = [int(l["target_id"]) for l in logs if l["target_type"] == "product" and str(l["target_id"]).isdigit()]
    shop_ids = [int(l["target_id"]) for l in logs if l["target_type"] == "shop" and str(l["target_id"]).isdigit()]
    products = fetch_by_ids(db, "products", product_ids, "id,name")
    shops = fetch_by_ids(db, "shops", shop_ids, "id,name")
    account_ids = [l["owner_id"] for l in logs if l.get("owner_id")]
    accounts = fetch_by_ids(db, "profiles", account_ids, "id,username,full_name")

    items = []
    for log in logs:
        owner = accounts.get(log.get("owner_id"))
        if log["target_type"] == "product":
            name = (products.get(int(log["target_id"])) or {}).get("name") if str(log["target_id"]).isdigit() else None
        elif log["target_type"] == "shop":
            name = (shops.get(int(log["target_id"])) or {}).get("name") if str(log["target_id"]).isdigit() else None
        else:
            name = (owner or {}).get("username")
        items.append({
            "id": log["id"], "created_at": log["created_at"], "target_type": log["target_type"],
            "target_name": name or "(đã bị xóa)", "owner_name": _owner_name(owner),
            "reasons": log.get("reasons") or [], "action": log["action"], "restored": bool(log.get("restored")),
        })

    pending = db.table("moderation_queue").select("id").eq("status", "pending").execute().data
    counts = {
        "blocked_today": sum(1 for l in logs if l["action"] == "blocked"),
        "pending": len(pending),
        "restored": sum(1 for l in logs if l.get("restored")),
    }
    return ok({"counts": counts, "items": items})


@bp.post("/ai-blocked/<int:log_id>/restore")
@require_role("admin")
def restore(log_id):
    """POST /api/admin/ai-blocked/{id}/restore: Admin cho rằng AI chặn nhầm, đưa đối tượng về bình thường.

    Sản phẩm, shop: về approved và đóng mục chờ duyệt. Tài khoản: mở khóa (active).
    """
    db = get_db()
    rows = db.table("ai_block_logs").select("*").eq("id", log_id).limit(1).execute().data
    if not rows:
        return fail("NOT_FOUND", "Không tìm thấy mục nhật ký.", 404)
    log = rows[0]
    if log.get("restored"):
        return fail("INVALID_STATE", "Mục này đã được khôi phục rồi.", 422)

    target_type, target_id = log["target_type"], log["target_id"]
    if target_type in ("product", "shop") and str(target_id).isdigit():
        table = "products" if target_type == "product" else "shops"
        db.table(table).update({"moderation_status": "approved"}).eq("id", int(target_id)).execute()
        db.table("moderation_queue").update({
            "status": "approved", "reviewed_by": g.user["id"], "reviewed_at": _now_iso(),
        }).eq("target_type", target_type).eq("target_id", int(target_id)).eq("status", "pending").execute()
    elif target_type == "account" and _valid_uuid(str(target_id)):
        db.table("profiles").update({"status": "active"}).eq("id", target_id).execute()

    db.table("ai_block_logs").update({"restored": True}).eq("id", log_id).execute()
    return ok({})