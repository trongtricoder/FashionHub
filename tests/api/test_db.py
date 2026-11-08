"""Test cấu hình kết nối Supabase (không gọi mạng)."""
import pytest

from api.services import db

URL = "https://abcdefgh.supabase.co"
KEY = "sb_secret_abcdefghijklmnopqrstuvwxyz123456"


def test_client_khong_dung_http2(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", URL)
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", KEY)
    db.get_db.cache_clear()
    try:
        session = db.get_db().postgrest.session
        pool = getattr(getattr(session, "_transport", None), "_pool", None)
        if pool is None or not hasattr(pool, "_http2"):
            pytest.skip("Phiên bản httpx này đổi cấu trúc nội bộ")
        assert pool._http2 is False
    finally:
        db.get_db.cache_clear()


def test_thieu_bien_moi_truong_bao_ro(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    db.get_db.cache_clear()
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        db.get_db()
    db.get_db.cache_clear()