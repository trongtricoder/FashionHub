"""Test thống kê dashboard Seller: nhãn ngày, tháng, múi giờ, KPI."""
from datetime import date

from ai.seller import stats

TODAY = date(2026, 10, 30)


def test_nhan_7_ngay_va_30_ngay():
    unit, labels = stats.labels_for("7d", TODAY)
    assert unit == "day" and labels[0] == "2026-10-24" and labels[-1] == "2026-10-30" and len(labels) == 7
    assert len(stats.labels_for("30d", TODAY)[1]) == 30 and stats.labels_for("30d", TODAY)[1][0] == "2026-10-01"


def test_nhan_12_thang_qua_nam():
    unit, labels = stats.labels_for("12m", TODAY)
    assert unit == "month" and labels[0] == "2025-11" and labels[-1] == "2026-10" and len(labels) == 12
    assert stats.labels_for("12m", date(2026, 1, 15))[1][0] == "2025-02"


def test_ngay_bat_dau_khoang():
    assert stats.range_start("7d", TODAY) == date(2026, 10, 24)
    assert stats.range_start("12m", TODAY) == date(2025, 11, 1)


def test_gio_viet_nam_chuyen_ngay():
    assert stats.vn_date("2026-10-29T17:30:00+00:00") == date(2026, 10, 30)   # 00:30 sáng GMT+7
    assert stats.vn_date("2026-10-29T16:30:00Z") == date(2026, 10, 29)
    assert stats.vn_date("2026-10-29T10:00:00") == date(2026, 10, 29)         # không có múi giờ thì coi là UTC


def test_dau_ngay_theo_gio_viet_nam_doi_sang_utc():
    assert stats.start_utc_iso(date(2026, 10, 30)) == "2026-10-29T17:00:00+00:00"


def test_dashboard_theo_ngay():
    views = [date(2026, 10, 30)] * 3 + [date(2026, 10, 29)] * 2 + [date(2026, 10, 1)]   # ngày 1/10 nằm ngoài 7 ngày
    completed = [(date(2026, 10, 30), 300000), (date(2026, 10, 30), 200000), (date(2026, 10, 24), 100000), (date(2026, 9, 1), 999)]
    d = stats.build_dashboard("7d", TODAY, views, completed, total_sold=40, total_stock=120)
    assert d["range"] == "7d" and len(d["labels"]) == 7
    assert d["views"][-1] == 3 and d["views"][-2] == 2 and sum(d["views"]) == 5
    assert d["revenue"][-1] == 500000 and d["revenue"][0] == 100000 and d["orders"][-1] == 2
    assert d["kpi"] == {"total_revenue": 600000, "total_orders": 3, "total_views": 5,
                        "conversion_rate": 0.6, "total_sold": 40, "total_stock": 120}
    assert d["forecast"] is None


def test_dashboard_theo_thang_gop_cac_ngay():
    views = [date(2026, 10, 3), date(2026, 10, 20), date(2026, 9, 5)]
    completed = [(date(2026, 10, 3), 100), (date(2026, 10, 20), 50), (date(2026, 9, 5), 10)]
    d = stats.build_dashboard("12m", TODAY, views, completed, 0, 0)
    assert d["labels"][-1] == "2026-10" and d["views"][-1] == 2 and d["views"][-2] == 1
    assert d["revenue"][-1] == 150 and d["revenue"][-2] == 10 and d["orders"][-1] == 2


def test_chua_co_luot_xem_thi_ty_le_bang_0():
    d = stats.build_dashboard("30d", TODAY, [], [(TODAY, 1000)], 0, 0)
    assert d["kpi"]["conversion_rate"] == 0.0 and d["kpi"]["total_revenue"] == 1000