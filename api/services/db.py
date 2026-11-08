"""Kết nối Supabase. Service role key chỉ nằm ở backend, tuyệt đối không đưa ra frontend."""
import os
from functools import lru_cache

import httpx
from supabase import Client, ClientOptions, create_client


def _env(name):
    """Đọc biến môi trường, báo lỗi rõ ràng nếu thiếu."""
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Thiếu biến môi trường {name}. Kiểm tra file .env")
    return value


def make_http_client():
    """Tạo httpx client dùng HTTP/1.1.

    Mặc định supabase-py dùng HTTP/2 và chia sẻ MỘT kết nối cho mọi luồng. Flask chạy mỗi request
    trên một luồng riêng, khi trình duyệt gọi nhiều API cùng lúc (giỏ hàng và đơn hàng) thì trên
    Windows kết nối HTTP/2 báo lỗi WinError 10035. HTTP/1.1 cấp kết nối riêng cho từng luồng nên không bị.
    retries=2 tự thử lại khi chưa kết nối được.
    """
    transport = httpx.HTTPTransport(
        http2=False,
        retries=2,
        limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
    )
    return httpx.Client(transport=transport, timeout=httpx.Timeout(20.0, connect=10.0))


def _options():
    """Tùy chọn client Supabase: dùng httpx client ở trên cho cả REST và Auth."""
    return ClientOptions(httpx_client=make_http_client())


@lru_cache(maxsize=1)
def get_db() -> Client:
    """Client dùng chung với service role key (bỏ qua RLS)."""
    return create_client(_env("SUPABASE_URL"), _env("SUPABASE_SERVICE_ROLE_KEY"), options=_options())


def new_anon_client() -> Client:
    """Client riêng cho đăng nhập, để phiên người dùng không dính vào client service role dùng chung."""
    return create_client(_env("SUPABASE_URL"), _env("SUPABASE_ANON_KEY"), options=_options())