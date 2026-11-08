"""Xác thực token Supabase và kiểm tra vai trò (mục 10.7)."""
from functools import wraps

from flask import current_app, g, request

from .db import get_db
from .responses import fail


def _bearer_token():
    """Lấy token từ header Authorization: Bearer <token>."""
    header = request.headers.get("Authorization", "")
    if header.lower().startswith("bearer "):
        return header[7:].strip() or None
    return None


def require_role(*roles, allow_banned=False):
    """Decorator: bắt buộc đăng nhập, đúng vai trò (nếu có chỉ định), không bị khóa.

    Sau khi qua, hồ sơ người dùng nằm ở g.user. Tài khoản banned bị từ chối mọi API,
    trừ nơi gọi allow_banned=True (GET /api/me).
    """
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            token = _bearer_token()
            if not token:
                return fail("UNAUTHENTICATED", "Bạn cần đăng nhập.", 401)

            db = get_db()
            try:
                user = db.auth.get_user(token).user
            except Exception:  # token sai hoặc hết hạn; ghi log để dễ lần lại khi lỗi thật
                current_app.logger.warning("Xác thực token thất bại", exc_info=True)
                user = None
            if not user:
                return fail("UNAUTHENTICATED", "Phiên đăng nhập không hợp lệ hoặc đã hết hạn.", 401)

            rows = db.table("profiles").select("*").eq("id", user.id).limit(1).execute().data
            if not rows:
                return fail("PROFILE_NOT_FOUND", "Tài khoản chưa có hồ sơ.", 403)
            profile = rows[0]

            if profile["status"] == "banned" and not allow_banned:
                return fail("ACCOUNT_BANNED", "Tài khoản của bạn đã bị khóa.", 403)
            if roles and profile["role"] not in roles:
                return fail("FORBIDDEN", "Bạn không có quyền thực hiện thao tác này.", 403)

            g.user = profile
            return fn(*args, **kwargs)
        return wrapper
    return decorator


def optional_user_id():
    """Id người dùng nếu request có token hợp lệ, ngược lại None (dùng cho API công khai như ghi sự kiện)."""
    token = _bearer_token()
    if not token:
        return None
    try:
        user = get_db().auth.get_user(token).user
        return user.id if user else None
    except Exception:  # token hết hạn thì coi như khách, không chặn request
        current_app.logger.info("Token không hợp lệ ở API công khai", exc_info=True)
        return None