"""Điểm vào của backend Flask. Chạy local: python -m flask --app api.index run --debug"""
import os

from dotenv import load_dotenv
from flask import Flask, request
from werkzeug.exceptions import HTTPException

from .services.responses import fail

load_dotenv()
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

HTTP_MESSAGES = {
    404: ("NOT_FOUND", "Không tìm thấy."),
    405: ("METHOD_NOT_ALLOWED", "Phương thức không được hỗ trợ."),
    413: ("FILE_TOO_LARGE", "Dữ liệu gửi lên quá lớn."),
}


def create_app():
    """Tạo app, đăng ký blueprint và xử lý lỗi chung."""
    # Phục vụ luôn các file HTML cũ để cùng một địa chỉ với API (khỏi lỗi CORS khi chạy local)
    static_dir = os.path.join(ROOT, os.environ.get("STATIC_DIR", "Project"))
    app = Flask(__name__, static_folder=static_dir, static_url_path="")
    app.config["MAX_CONTENT_LENGTH"] = 6 * 1024 * 1024  # chặn request quá lớn (ảnh tối đa 5 MB cộng phần đầu form)

    from .routes import admin, ai, auth, cart, events, me, orders, products, seller, seller_catalog, seller_dashboard
    for module in (admin, ai, auth, cart, events, me, orders, products, seller, seller_catalog, seller_dashboard):
        app.register_blueprint(module.bp)

    @app.get("/")
    def home():
        return app.send_static_file("Home.html")

    @app.errorhandler(HTTPException)
    def http_error(err):
        if request.path.startswith("/api/"):
            code, message = HTTP_MESSAGES.get(err.code, ("HTTP_ERROR", err.description))
            return fail(code, message, err.code)
        return err

    @app.errorhandler(Exception)
    def unexpected_error(err):
        app.logger.exception("Lỗi không lường trước")
        if request.path.startswith("/api/"):
            return fail("SERVER_ERROR", "Máy chủ gặp lỗi, vui lòng thử lại sau.", 500)
        return "Lỗi máy chủ", 500

    return app


app = create_app()