"""Test công thức giao hàng dự kiến (mục 10.4)."""
from api.services import eta


def test_cung_toa_do_thi_eta_bang_thoi_gian_chuan_bi():
    assert eta.eta_minutes(30, 10.77, 106.70, 10.77, 106.70) == 30


def test_thieu_toa_do_tra_none():
    assert eta.eta_minutes(30, 10.77, 106.70, None, None) is None
    assert eta.eta_minutes(30, None, None, 10.77, 106.70) is None
    assert eta.road_distance_km(None, 106.7, 10.7, 106.7) is None


def test_khoang_cach_quan_1_den_quan_7():
    # Khoảng 6,5 km đường chim bay giữa Quận 1 và Quận 7, nhân 1.3 là đường vòng
    direct = eta.haversine_km(10.7769, 106.7009, 10.7340, 106.7220)
    assert 5.0 < direct < 6.5
    road = eta.road_distance_km(10.7769, 106.7009, 10.7340, 106.7220)
    assert abs(road - direct * 1.3) < 1e-9


def test_eta_theo_cong_thuc():
    road = eta.road_distance_km(10.7769, 106.7009, 10.7340, 106.7220)
    assert eta.eta_minutes(30, 10.7769, 106.7009, 10.7340, 106.7220) == round(30 + road / 25 * 60)


def test_expected_at_cong_phut():
    assert eta.expected_at("2026-10-28T03:00:00+00:00", 45) == "2026-10-28T03:45:00+00:00"
    assert eta.expected_at("2026-10-28T03:00:00Z", 45) == "2026-10-28T03:45:00+00:00"
    assert eta.expected_at("2026-10-28T03:00:00+00:00", None) is None