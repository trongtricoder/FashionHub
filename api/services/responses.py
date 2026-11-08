"""Định dạng phản hồi chung (mục 9.0 của PROJECT_CONTEXT)."""
from flask import jsonify


def ok(data=None, status=200):
    """Trả về thành công: { ok: true, data }."""
    return jsonify({"ok": True, "data": {} if data is None else data}), status


def fail(code, message, status=400):
    """Trả về lỗi: { ok: false, error: { code, message } }, message bằng tiếng Việt."""
    return jsonify({"ok": False, "error": {"code": code, "message": message}}), status


def ok_null():
    """Thành công nhưng chưa có dữ liệu: { ok: true, data: null } (ví dụ chưa nhập số đo). Khác ok() vì ok() đổi None thành {}."""
    return jsonify({"ok": True, "data": None}), 200