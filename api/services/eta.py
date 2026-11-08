"""Tính khoảng cách và thời gian giao dự kiến (mục 10.4 của PROJECT_CONTEXT)."""
import math
from datetime import datetime, timedelta

ROAD_FACTOR = 1.3   # hệ số đường vòng so với đường chim bay
SPEED_KMH = 25      # tốc độ trung bình nội thành


def haversine_km(lat1, lng1, lat2, lng2):
    """Khoảng cách đường chim bay (km) giữa hai tọa độ."""
    radius = 6371.0
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    d_phi = phi2 - phi1
    d_lambda = math.radians(lng2 - lng1)
    a = math.sin(d_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(d_lambda / 2) ** 2
    return 2 * radius * math.asin(math.sqrt(a))


def road_distance_km(shop_lat, shop_lng, lat, lng):
    """Quãng đường ước tính (đã nhân hệ số đường vòng). Thiếu tọa độ thì trả về None."""
    if None in (shop_lat, shop_lng, lat, lng):
        return None
    return haversine_km(shop_lat, shop_lng, lat, lng) * ROAD_FACTOR


def eta_minutes(prep_minutes, shop_lat, shop_lng, lat, lng):
    """Số phút giao dự kiến = thời gian chuẩn bị + quãng đường / tốc độ. Thiếu tọa độ thì None."""
    distance = road_distance_km(shop_lat, shop_lng, lat, lng)
    if distance is None:
        return None
    return round(prep_minutes + distance / SPEED_KMH * 60)


def expected_at(created_at_iso, eta):
    """Thời điểm giao dự kiến (ISO) = created_at + eta_minutes. Thiếu dữ liệu thì None."""
    if eta is None or not created_at_iso:
        return None
    created = datetime.fromisoformat(created_at_iso.replace("Z", "+00:00"))
    return (created + timedelta(minutes=eta)).isoformat()