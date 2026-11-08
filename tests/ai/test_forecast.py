"""Test dự đoán doanh thu 7 ngày tới: hồi quy tuyến tính và hệ số theo thứ trong tuần."""
from datetime import date, timedelta

from ai.seller import forecast

TODAY = date(2026, 10, 30)   # thứ Sáu


def series(fn, days=30):
    return {TODAY - timedelta(days=days - 1 - i): fn(i, TODAY - timedelta(days=days - 1 - i)) for i in range(days)}


def test_nhan_la_7_ngay_ke_tiep():
    result = forecast.forecast_revenue(series(lambda i, d: 1000000), TODAY)
    assert result["labels"] == ["2026-10-31", "2026-11-01", "2026-11-02", "2026-11-03", "2026-11-04", "2026-11-05", "2026-11-06"]
    assert len(result["revenue"]) == 7


def test_doanh_thu_deu_thi_du_doan_xap_xi_deu():
    result = forecast.forecast_revenue(series(lambda i, d: 1000000), TODAY)
    assert all(abs(v - 1000000) < 1000 for v in result["revenue"])


def test_xu_huong_tang_thi_du_doan_tiep_tuc_tang():
    result = forecast.forecast_revenue(series(lambda i, d: 1000000 + i * 50000), TODAY)
    revenue = result["revenue"]
    assert revenue[0] > 1000000 + 29 * 50000 - 1000      # tiếp tục tăng, không bị hệ số thứ kéo xuống
    assert max(revenue) > revenue[0]


def test_xu_huong_giam_manh_khong_xuong_duoi_0():
    result = forecast.forecast_revenue(series(lambda i, d: max(0, 3000000 - i * 120000)), TODAY)
    assert all(v >= 0 for v in result["revenue"])


def test_cuoi_tuan_ban_nhieu_hon_thi_du_doan_cuoi_tuan_cao_hon():
    result = forecast.forecast_revenue(series(lambda i, d: 3000000 if d.weekday() >= 5 else 1000000), TODAY)
    by_weekday = {date.fromisoformat(l).weekday(): v for l, v in zip(result["labels"], result["revenue"])}
    assert by_weekday[5] > 2 * by_weekday[1] and by_weekday[6] > 2 * by_weekday[2]   # thứ 7, CN so với thứ 3, thứ 4


def test_he_so_theo_thu_trung_binh_gan_1():
    days = [TODAY - timedelta(days=29 - i) for i in range(30)]
    values = [3000000.0 if d.weekday() >= 5 else 1000000.0 for d in days]
    factors = forecast.weekday_factors(days, values)
    assert factors[5] > 1 > factors[1]
    assert abs(sum(factors.values()) / 7 - 1) < 0.15


def test_chua_co_doanh_thu_thi_du_doan_bang_0():
    assert forecast.forecast_revenue({}, TODAY)["revenue"] == [0] * 7


def test_ngay_thieu_coi_nhu_0_va_ket_qua_la_so_nguyen():
    result = forecast.forecast_revenue({TODAY: 2500000, TODAY - timedelta(days=7): 1500000}, TODAY)
    assert all(isinstance(v, int) and v >= 0 for v in result["revenue"])


def test_he_so_thu_khong_bi_xu_huong_lam_sai_lech():
    """Doanh thu tăng đều thì mọi thứ trong tuần đều có hệ số xấp xỉ 1 (trước đây thứ nằm đầu chuỗi bị coi là yếu)."""
    days = [TODAY - timedelta(days=29 - i) for i in range(30)]
    values = [1000000.0 + i * 50000 for i in range(30)]
    trend = list(values)       # xu hướng chính là chuỗi tăng đều
    factors = forecast.weekday_factors(days, values, trend)
    assert all(abs(f - 1) < 1e-9 for f in factors.values())