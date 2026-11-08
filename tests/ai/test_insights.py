"""Test gợi ý theo luật cho Seller (mục 10.5)."""
from datetime import date

from ai.seller import insights


def make_ctx(**kw):
    ctx = {"today": date(2026, 10, 30), "products": [], "variants": [], "revenue_last7": 0, "revenue_prev7": 0,
           "revenue_30d": 0, "orders_by_status": {}, "total_stock": 0, "shape_counts": {}}
    ctx.update(kw)
    return ctx


def product(pid, name, stock=10, sold=0, views=0, purchases=0):
    return {"id": pid, "name": name, "stock_total": stock, "sold_30d": sold, "views_30d": views, "purchases_30d": purchases}


def variant(vid, name, stock, sold_14d, size="M", color="Trắng"):
    return {"variant_id": vid, "product_id": vid, "name": name, "size": size, "color": color, "stock": stock, "sold_14d": sold_14d}


def titles(result):
    return [s["title"] for s in result["suggestions"]]


def test_shop_chua_co_du_lieu_khong_co_goi_y():
    result = insights.generate(make_ctx())
    assert result["suggestions"] == []
    assert "Chưa có doanh thu" in result["summary"]


def test_sap_het_hang_va_dang_ban_thi_goi_y_nhap_them():
    ctx = make_ctx(variants=[variant(1, "Áo thun", stock=3, sold_14d=5), variant(2, "Quần jeans", stock=4, sold_14d=0),
                             variant(3, "Váy", stock=9, sold_14d=7)])
    result = insights.generate(ctx)
    assert titles(result) == ["Nên nhập thêm Áo thun (size M, màu Trắng)"]      # quần không bán nên bỏ, váy còn nhiều nên bỏ
    assert result["suggestions"][0]["severity"] == "warning" and "đã bán 5" in result["suggestions"][0]["detail"]


def test_ranh_gioi_ton_kho_5_van_tinh_la_sap_het():
    assert len(insights.low_stock_items(make_ctx(variants=[variant(1, "A", 5, 1), variant(2, "B", 6, 1)]))) == 1


def test_hang_ton_cham_goi_y_giam_gia():
    ctx = make_ctx(products=[product(1, "Áo A", stock=30, sold=1), product(2, "Áo B", stock=30, sold=2),
                             product(3, "Áo C", stock=19, sold=0)])
    assert "Cân nhắc giảm giá Áo A" in titles(insights.generate(ctx))
    assert [p["name"] for p in insights.slow_stock_items(ctx)] == ["Áo A"]      # B bán đủ 2, C tồn dưới 20


def test_nhieu_xem_it_mua_goi_y_cai_thien_anh_mo_ta():
    ctx = make_ctx(products=[product(1, "Áo A", views=150, purchases=2), product(2, "Áo B", views=99, purchases=0),
                             product(3, "Áo C", views=200, purchases=10)])
    items = insights.low_conversion_items(ctx)
    assert [p["name"] for p in items] == ["Áo A"]          # B chưa đủ 100 lượt xem, C tỷ lệ mua 5%
    result = insights.generate(ctx)
    assert "Cải thiện ảnh và mô tả Áo A" in titles(result)
    assert next(s for s in result["suggestions"] if "Áo A" in s["title"])["severity"] == "info"


def test_xu_huong_doanh_thu_tang_giam_on_dinh():
    up = insights.generate(make_ctx(revenue_last7=1200000, revenue_prev7=1000000))
    assert "Doanh thu tăng 20% so với tuần trước" in titles(up) and up["suggestions"][0]["severity"] == "success"
    down = insights.generate(make_ctx(revenue_last7=500000, revenue_prev7=1000000))
    assert "Doanh thu giảm 50% so với tuần trước" in titles(down) and down["suggestions"][0]["severity"] == "warning"
    flat = insights.generate(make_ctx(revenue_last7=1050000, revenue_prev7=1000000))
    assert not any("Doanh thu" in t for t in titles(flat))
    assert "ổn định" in flat["summary"]
    first_week = insights.generate(make_ctx(revenue_last7=800000, revenue_prev7=0))
    assert any("Doanh thu tăng" in t for t in titles(first_week))


def test_top_ban_chay_toi_da_3_sap_theo_so_luong():
    ctx = make_ctx(products=[product(i, f"SP{i}", sold=s) for i, s in enumerate([5, 9, 7, 1, 0], start=1)])
    names = [p["name"] for p in insights.best_sellers(ctx)]
    assert names == ["SP2", "SP3", "SP1"]
    detail = next(s for s in insights.generate(ctx)["suggestions"] if s["title"].startswith("Đẩy mạnh"))["detail"]
    assert detail == "Top bán chạy 30 ngày qua: SP2 (9), SP3 (7), SP1 (5)."


def test_dang_nguoi_pho_bien():
    ctx = make_ctx(shape_counts={"pear": 3, "hourglass": 1})
    result = insights.generate(ctx)
    assert "Nhập thêm đồ hợp dáng quả lê" in titles(result)
    assert "75%" in next(s for s in result["suggestions"] if "quả lê" in s["title"])["detail"]
    assert insights.popular_shape(make_ctx()) is None


def test_goi_y_xep_canh_bao_truoc_roi_thanh_cong_roi_thong_tin():
    ctx = make_ctx(variants=[variant(1, "Áo thun", 2, 4)], products=[product(1, "Áo thun", sold=9)],
                   revenue_last7=2000000, revenue_prev7=1000000, shape_counts={"apple": 2})
    severities = [s["severity"] for s in insights.generate(ctx)["suggestions"]]
    assert severities == sorted(severities, key=lambda s: {"warning": 0, "success": 1, "info": 2}[s])
    assert severities[0] == "warning" and severities[-1] == "info"


def test_moi_luat_toi_da_3_san_pham():
    ctx = make_ctx(variants=[variant(i, f"SP{i}", 1, 1) for i in range(1, 8)])
    assert len(insights.generate(ctx)["suggestions"]) == 3


def test_tom_tat_ngan_gon_toi_da_3_cau():
    ctx = make_ctx(products=[product(1, "Áo A", stock=30, sold=0), product(2, "Áo B", sold=8)],
                   revenue_last7=2000000, revenue_prev7=1000000)
    summary = insights.generate(ctx)["summary"]
    assert summary.count(". ") <= 2 and "tăng 100%" in summary and "Áo B" in summary and "giảm giá Áo A" in summary