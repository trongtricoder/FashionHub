"""Hồ sơ người dùng hiện tại: GET và PATCH /api/me (mục 9.1)."""
import re
import uuid

from flask import Blueprint, current_app, g, request

from ..services import product_input, uploads
from ..services.auth import require_role
from ..services.db import get_db, new_anon_client
from ..services.responses import fail, ok, ok_null

bp = Blueprint("me", __name__, url_prefix="/api/me")

PHONE_RE = re.compile(r"^(\+84|0)\d{9,10}$")
MAX_AVATAR_BYTES = 2 * 1024 * 1024


def me_payload(profile):
    """Dựng dữ liệu /api/me từ hồ sơ. Seller có thêm shop_id."""
    data = {k: profile.get(k) for k in (
        "id", "username", "email", "full_name", "phone", "address", "avatar_url",
        "role", "status", "must_change_password")}
    if profile["role"] == "seller":
        shops = get_db().table("shops").select("id").eq("owner_id", profile["id"]).limit(1).execute().data
        data["shop_id"] = shops[0]["id"] if shops else None
    return data


@bp.get("")
@require_role(allow_banned=True)  # tài khoản bị khóa vẫn xem được để giao diện hiện thông báo
def get_me():
    """Trả về hồ sơ của chính mình."""
    return ok(me_payload(g.user))


@bp.patch("")
@require_role()
def update_me():
    """Sửa full_name, phone, address, avatar_url. Chỉ nhận các trường này."""
    body = request.get_json(silent=True) or {}
    updates = {}

    if "full_name" in body:
        value = str(body["full_name"] or "").strip()
        if len(value) > 100:
            return fail("INVALID_INPUT", "Họ tên tối đa 100 ký tự.", 400)
        updates["full_name"] = value
    if "phone" in body:
        value = str(body["phone"] or "").replace(" ", "")
        if value and not PHONE_RE.match(value):
            return fail("INVALID_INPUT", "Số điện thoại không hợp lệ.", 400)
        updates["phone"] = value
    if "address" in body:
        value = str(body["address"] or "").strip()
        if len(value) > 255:
            return fail("INVALID_INPUT", "Địa chỉ tối đa 255 ký tự.", 400)
        updates["address"] = value
    if "avatar_url" in body:
        value = str(body["avatar_url"] or "").strip()
        if value and not value.startswith(("http://", "https://")):
            return fail("INVALID_INPUT", "Ảnh đại diện phải là đường dẫn http hoặc https.", 400)
        updates["avatar_url"] = value[:500]

    if not updates:
        return fail("INVALID_INPUT", "Không có thông tin nào để cập nhật.", 400)

    rows = get_db().table("profiles").update(updates).eq("id", g.user["id"]).execute().data
    return ok(me_payload(rows[0]))


@bp.post("/avatar")
@require_role()
def upload_avatar():
    """POST /api/me/avatar (multipart, field 'file'): upload avatar to public Supabase Storage."""
    file = request.files.get("file")
    if not file:
        return fail("INVALID_INPUT", "Vui lòng chọn ảnh đại diện.", 400)
    data = file.read(MAX_AVATAR_BYTES + 1)
    if len(data) > MAX_AVATAR_BYTES:
        return fail("FILE_TOO_LARGE", "Ảnh đại diện tối đa 2 MB.", 413)
    kind = uploads.sniff_image(data)
    if not kind:
        return fail("INVALID_INPUT", "Ảnh đại diện phải là JPG, PNG hoặc WEBP.", 400)

    extension, content_type = kind
    path = f"{g.user['id']}/{uuid.uuid4().hex}.{extension}"
    db = get_db()
    try:
        storage = db.storage.from_("avatars")
        storage.upload(path, data, {"content-type": content_type})
        avatar_url = storage.get_public_url(path).rstrip("?")
    except Exception:
        current_app.logger.exception("Tải ảnh đại diện lên Supabase Storage thất bại")
        return fail("UPLOAD_FAILED", "Không tải được ảnh đại diện, vui lòng thử lại.", 502)

    rows = db.table("profiles").update({"avatar_url": avatar_url}).eq(
        "id", g.user["id"]).execute().data
    return ok(me_payload(rows[0]))


@bp.post("/change-password")
@require_role()
def change_password():
    """Verify the current password, update the password, and clear the forced-change flag.

    Thay cho POST /api/me/password-changed ở mục 9.1, vì trang HTML không dùng Supabase JS để tự đổi mật khẩu.
    """
    body = request.get_json(silent=True) or {}
    current_password = str(body.get("current_password") or "")
    password = str(body.get("new_password") or "")
    if not current_password or len(current_password) > 72:
        return fail("INVALID_INPUT", "Vui lòng nhập mật khẩu hiện tại.", 400)
    if not 6 <= len(password) <= 72:
        return fail("INVALID_INPUT", "Mật khẩu mới phải từ 6 đến 72 ký tự.", 400)
    if current_password == password:
        return fail("INVALID_INPUT", "Mật khẩu mới phải khác mật khẩu hiện tại.", 400)

    try:
        verification = new_anon_client().auth.sign_in_with_password({
            "email": g.user["email"],
            "password": current_password,
        })
    except Exception:
        current_app.logger.info("Xác minh mật khẩu hiện tại thất bại cho %s", g.user["id"])
        return fail("INVALID_CURRENT_PASSWORD", "Mật khẩu hiện tại không đúng.", 401)
    if not verification.session:
        return fail("INVALID_CURRENT_PASSWORD", "Mật khẩu hiện tại không đúng.", 401)

    db = get_db()
    try:
        db.auth.admin.update_user_by_id(g.user["id"], {"password": password})
    except Exception:
        current_app.logger.exception("Đổi mật khẩu thất bại")
        return fail("PASSWORD_FAILED", "Không đổi được mật khẩu, vui lòng thử lại.", 502)
    if g.user.get("must_change_password"):
        db.table("profiles").update({"must_change_password": False}).eq("id", g.user["id"]).execute()
    return ok({})


@bp.get("/body-profile")
@require_role("buyer")
def get_body_profile():
    """GET /api/me/body-profile: số đo đã lưu, hoặc null nếu chưa nhập."""
    rows = get_db().table("body_profiles").select("*").eq("user_id", g.user["id"]).limit(1).execute().data
    return ok(rows[0]) if rows else ok_null()


@bp.put("/body-profile")
@require_role("buyer")
def put_body_profile():
    """PUT /api/me/body-profile: lưu số đo (tạo mới hoặc cập nhật). Dùng cho gợi ý sản phẩm và thử đồ."""
    try:
        clean = product_input.parse_body_profile(request.get_json(silent=True) or {})
    except product_input.InputError as err:
        return fail("INVALID_INPUT", str(err), 400)
    db = get_db()
    existing = db.table("body_profiles").select("user_id").eq("user_id", g.user["id"]).limit(1).execute().data
    if existing:
        row = db.table("body_profiles").update(clean).eq("user_id", g.user["id"]).execute().data[0]
    else:
        row = db.table("body_profiles").insert(dict(clean, user_id=g.user["id"])).execute().data[0]
    return ok(row)