"""Đăng nhập và đăng ký.

Khác hợp đồng mục 9.1 (ghi vào mục 15): giao diện cũ đăng nhập bằng username nên backend
nhận username hoặc email, tự tra email rồi đăng nhập Supabase. Nhờ vậy trang HTML
không cần nhúng Supabase JS hay khóa anon.
"""
import re

from flask import Blueprint, current_app, request

from ..services.db import get_db, new_anon_client
from ..services.responses import fail, ok
from .me import me_payload

bp = Blueprint("auth", __name__, url_prefix="/api/auth")

USERNAME_RE = re.compile(r"^[A-Za-z0-9_.]{3,30}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@bp.post("/login")
def login():
    """Đăng nhập bằng username hoặc email. Trả về token và hồ sơ."""
    body = request.get_json(silent=True) or {}
    identifier = str(body.get("identifier") or "").strip()
    password = str(body.get("password") or "")
    if not identifier or not password:
        return fail("INVALID_INPUT", "Vui lòng nhập tên đăng nhập và mật khẩu.", 400)

    db = get_db()
    column, value = ("email", identifier.lower()) if "@" in identifier else ("username", identifier)
    rows = db.table("profiles").select("*").eq(column, value).limit(1).execute().data
    wrong = fail("INVALID_CREDENTIALS", "Sai tên đăng nhập hoặc mật khẩu.", 401)
    if not rows:
        return wrong  # cùng một thông báo để không lộ tài khoản nào tồn tại
    profile = rows[0]

    try:
        session = new_anon_client().auth.sign_in_with_password(
            {"email": profile["email"], "password": password}).session
    except Exception:  # sai mật khẩu hoặc lỗi từ Supabase Auth
        current_app.logger.info("Đăng nhập thất bại cho %s", profile["username"], exc_info=True)
        return wrong
    if not session:
        return wrong

    if profile["status"] == "banned":
        return fail("ACCOUNT_BANNED", "Tài khoản của bạn đã bị khóa. Vui lòng liên hệ Admin.", 403)

    return ok({
        "access_token": session.access_token,
        "refresh_token": session.refresh_token,
        "expires_at": session.expires_at,
        "me": me_payload(profile),
    })


@bp.post("/register")
def register():
    """Đăng ký buyer hoặc seller. Seller được tạo luôn một shop trống. Không cho tự đăng ký admin."""
    body = request.get_json(silent=True) or {}
    username = str(body.get("username") or "").strip()
    email = str(body.get("email") or "").strip().lower()
    password = str(body.get("password") or "")
    role = body.get("role")
    full_name = str(body.get("full_name") or "").strip()[:100]
    phone = str(body.get("phone") or "").replace(" ", "")

    if not USERNAME_RE.match(username):
        return fail("INVALID_INPUT", "Tên đăng nhập gồm 3 đến 30 ký tự: chữ, số, dấu chấm hoặc gạch dưới.", 400)
    if not EMAIL_RE.match(email):
        return fail("INVALID_INPUT", "Email không hợp lệ.", 400)
    if len(password) < 6:
        return fail("INVALID_INPUT", "Mật khẩu tối thiểu 6 ký tự.", 400)
    if role not in ("buyer", "seller"):
        return fail("INVALID_INPUT", "Vai trò chỉ có thể là người mua hoặc người bán.", 400)

    db = get_db()
    if db.table("profiles").select("id").eq("username", username).limit(1).execute().data:
        return fail("USERNAME_TAKEN", "Tên đăng nhập đã được sử dụng.", 409)
    if db.table("profiles").select("id").eq("email", email).limit(1).execute().data:
        return fail("EMAIL_TAKEN", "Email đã được sử dụng.", 409)

    try:
        user = db.auth.admin.create_user(
            {"email": email, "password": password, "email_confirm": True}).user
    except Exception:
        current_app.logger.exception("Không tạo được tài khoản Supabase Auth")
        return fail("REGISTER_FAILED", "Không tạo được tài khoản, vui lòng thử lại.", 422)

    try:
        db.table("profiles").insert({
            "id": user.id, "username": username, "email": email,
            "full_name": full_name or username, "phone": phone or None, "role": role,
        }).execute()
        if role == "seller":
            db.table("shops").insert({"owner_id": user.id, "name": f"Shop {username}"}).execute()
    except Exception:
        # Hoàn tác để không còn tài khoản Auth mồ côi không có hồ sơ
        current_app.logger.exception("Lỗi khi tạo hồ sơ, xóa tài khoản Auth vừa tạo")
        db.auth.admin.delete_user(user.id)
        return fail("REGISTER_FAILED", "Không tạo được hồ sơ, vui lòng thử lại.", 422)

    return ok({"username": username, "role": role}, 201)