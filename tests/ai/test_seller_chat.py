"""Test AI đồng hành của Seller: nhận diện ý định và trả lời bằng số liệu thật."""
from datetime import date

import pytest

from ai.seller import chat
from tests.ai.test_insights import make_ctx, product, variant


def ctx():
    return make_ctx(
        products=[product(1, "Áo thun", stock=30, sold=1), product(2, "Áo khoác", sold=12), product(3, "Quần jeans", sold=7)],
        variants=[variant(1, "Áo khoác", stock=2, sold_14d=6, size="L", color="Đen")],
        revenue_last7=1500000, revenue_30d=6200000, total_stock=88,
        orders_by_status={"pending": 3, "processing": 2, "shipping": 1, "completed": 20, "cancelled": 4})


@pytest.mark.parametrize("message,intent", [
    ("Doanh thu tuần này là bao nhiêu?", "revenue"), ("doanh số", "revenue"),
    ("Tồn kho còn bao nhiêu", "stock"), ("sản phẩm nào sắp hết hàng", "stock"),
    ("Còn bao nhiêu áo thể thao trong kho?", "stock"),
    ("Sản phẩm bán chạy nhất?", "best"), ("top sản phẩm", "best"),
    ("Hàng nào ế nhất", "slow"), ("hàng bán chậm quá", "slow"), ("nên giảm giá gì", "slow"),
    ("Có bao nhiêu đơn hàng", "orders"),
    ("Còn bao nhiêu đơn hàng?", "orders"),
    ("Cho mình gợi ý cải thiện", "insights"), ("tư vấn giúp mình", "insights"),
    ("xin chào", None), ("chào bạn", None),           # chữ "e" không được khớp bên trong từ khác
])
def test_nhan_dien_y_dinh(message, intent):
    assert chat.detect_intent(message) == intent


def test_tra_loi_doanh_thu_bang_so_that():
    reply = chat.answer("doanh thu", ctx())
    assert "1.500.000đ" in reply and "6.200.000đ" in reply


def test_tra_loi_ton_kho_co_mat_hang_sap_het():
    reply = chat.answer("tồn kho", ctx())
    assert "88" in reply and "Áo khoác (L, Đen): còn 2" in reply
    assert "Chưa có mặt hàng" in chat.answer("tồn kho", make_ctx(total_stock=10))


def test_tra_loi_ton_kho_theo_ten_san_pham_va_bien_the():
    context = make_ctx(
        products=[product(1, "Áo thể thao nam", stock=12)],
        variants=[variant(1, "Áo thể thao nam", stock=7, sold_14d=0, size="M", color="Đen"),
                  {**variant(2, "Áo thể thao nam", stock=5, sold_14d=0, size="L", color="Đỏ"), "product_id": 1}],
        total_stock=12,
    )
    reply = chat.answer("Còn bao nhiêu áo thể thao tồn kho?", context)
    assert "Áo thể thao nam: còn 12" in reply
    assert "M, Đen: 7" in reply and "L, Đỏ: 5" in reply


def test_tra_loi_ban_chay_theo_thu_tu():
    reply = chat.answer("bán chạy", ctx())
    assert reply.index("Áo khoác") < reply.index("Quần jeans") and "(12)" in reply
    assert "chưa bán được" in chat.answer("bán chạy", make_ctx())


def test_tra_loi_hang_ton_cham():
    assert "Áo thun (tồn 30, bán 1)" in chat.answer("hàng nào ế", ctx())
    assert "không có sản phẩm nào" in chat.answer("hàng nào ế", make_ctx())


def test_tra_loi_don_hang_theo_trang_thai():
    reply = chat.answer("đơn hàng", ctx())
    assert "3 chờ xác nhận" in reply and "20 hoàn tất" in reply and "4 đã hủy" in reply


def test_tra_loi_goi_y_goi_lai_insights():
    reply = chat.answer("cho mình gợi ý", ctx())
    assert reply.count("\n") >= 1 and "Nên nhập thêm Áo khoác" in reply


def test_khong_hieu_thi_goi_y_cau_hoi_co_the_hoi():
    assert chat.answer("blah blah", ctx()) == chat.HELP and "doanh thu" in chat.HELP