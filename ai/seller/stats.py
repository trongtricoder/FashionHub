"""Thống kê cho dashboard Seller (mục 9.5): gom dữ liệu thô theo ngày hoặc theo tháng.

Hàm thuần, không gọi database. Mọi mốc thời gian tính theo giờ Việt Nam (GMT+7, mục 1).
"""
from datetime import date, datetime, timedelta, timezone

VN_TZ = timezone(timedelta(hours=7))
RANGES = {"7d": ("day", 7), "30d": ("day", 30), "12m": ("month", 12)}


def vn_date(iso_text):
    """Ngày (giờ Việt Nam) của một mốc thời gian dạng ISO. Mốc không có múi giờ được coi là UTC."""
    moment = datetime.fromisoformat(iso_text.replace("Z", "+00:00"))
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=timezone.utc)
    return moment.astimezone(VN_TZ).date()


def shift_months(first_of_month, months):
    """Ngày mùng 1 của tháng cách first_of_month một số tháng (có thể âm)."""
    index = first_of_month.year * 12 + (first_of_month.month - 1) + months
    return date(index // 12, index % 12 + 1, 1)


def labels_for(range_key, today):
    """Trả về (đơn vị, danh sách nhãn) của khoảng thời gian: ngày 'YYYY-MM-DD' hoặc tháng 'YYYY-MM'."""
    unit, count = RANGES[range_key]
    if unit == "day":
        days = [today - timedelta(days=count - 1 - i) for i in range(count)]
        return unit, [d.isoformat() for d in days]
    first = date(today.year, today.month, 1)
    months = [shift_months(first, -(count - 1 - i)) for i in range(count)]
    return unit, [m.strftime("%Y-%m") for m in months]


def range_start(range_key, today):
    """Ngày đầu tiên của khoảng thời gian (mùng 1 nếu tính theo tháng)."""
    _, labels = labels_for(range_key, today)
    parts = [int(p) for p in labels[0].split("-")]
    return date(parts[0], parts[1], parts[2] if len(parts) == 3 else 1)


def start_utc_iso(day):
    """Đầu ngày (00:00 giờ Việt Nam) của một ngày, đổi sang UTC để dùng làm điều kiện truy vấn."""
    start = datetime(day.year, day.month, day.day, tzinfo=VN_TZ)
    return start.astimezone(timezone.utc).isoformat()


def bucket(day, unit):
    return day.isoformat() if unit == "day" else day.strftime("%Y-%m")


def build_dashboard(range_key, today, view_dates, completed, total_sold, total_stock, forecast=None):
    """Dựng phản hồi dashboard.

    view_dates: ngày của từng lượt xem. completed: danh sách (ngày hoàn tất, tiền shop nhận) của đơn hoàn tất.
    Doanh thu là số tiền shop nhận sau phí nền tảng, tính theo ngày đơn hoàn tất.
    """
    unit, labels = labels_for(range_key, today)
    position = {label: i for i, label in enumerate(labels)}
    views, revenue, orders = [0] * len(labels), [0] * len(labels), [0] * len(labels)

    for day in view_dates:
        i = position.get(bucket(day, unit))
        if i is not None:
            views[i] += 1
    for day, total in completed:
        i = position.get(bucket(day, unit))
        if i is not None:
            revenue[i] += total
            orders[i] += 1

    total_views, total_orders = sum(views), sum(orders)
    return {
        "range": range_key,
        "labels": labels,
        "views": views,
        "revenue": revenue,
        "orders": orders,
        "kpi": {
            "total_revenue": sum(revenue),
            "total_orders": total_orders,
            "total_views": total_views,
            # tỷ lệ chuyển đổi = số đơn / số lượt xem trong khoảng (mục 9.5)
            "conversion_rate": round(total_orders / total_views, 4) if total_views else 0.0,
            "total_sold": total_sold,
            "total_stock": total_stock,
        },
        "forecast": forecast,
    }