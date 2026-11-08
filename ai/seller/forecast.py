"""Dự đoán doanh thu 7 ngày tới (mục 10.5, mức 1): hồi quy tuyến tính có điều chỉnh theo thứ trong tuần."""
from datetime import timedelta

import numpy as np

HISTORY_DAYS = 30   # số ngày quá khứ dùng để học
HORIZON = 7         # số ngày dự đoán


def weekday_factors(days, values, trend=None):
    """Hệ số theo thứ: doanh thu thật của thứ đó chia cho mức "bình thường" của chính những ngày đó.

    Mức bình thường là đường xu hướng (nếu có) hoặc trung bình chung. So với đường xu hướng thì doanh thu đang tăng
    không làm sai lệch hệ số: ví dụ thứ Hai nằm đầu chuỗi sẽ không bị tính là "ngày yếu" chỉ vì lúc đó doanh thu còn thấp.
    """
    if trend is None:
        overall = sum(values) / len(values) if values else 0
        trend = [overall] * len(values)
    factors = {}
    for weekday in range(7):
        actual = sum(v for d, v in zip(days, values) if d.weekday() == weekday)
        normal = sum(max(t, 0) for d, t in zip(days, trend) if d.weekday() == weekday)
        factors[weekday] = actual / normal if normal > 0 else 1.0
    return factors


def forecast_revenue(daily_revenue, today, horizon=HORIZON, history=HISTORY_DAYS):
    """Dự đoán doanh thu từng ngày trong `horizon` ngày tới.

    daily_revenue: dict { ngày: doanh thu }, ngày thiếu coi như 0.
    Đường xu hướng y = a*x + b chạy bằng numpy.polyfit trên `history` ngày gần nhất, nhân với hệ số của thứ
    trong tuần (cuối tuần bán nhiều hơn thì hệ số lớn hơn 1), kết quả không âm. Chưa có doanh thu thì trả về 0.
    Trả về { labels, revenue }.
    """
    days = [today - timedelta(days=history - 1 - i) for i in range(history)]
    values = [float(daily_revenue.get(d, 0)) for d in days]
    future = [today + timedelta(days=k) for k in range(1, horizon + 1)]
    labels = [d.isoformat() for d in future]
    if sum(values) <= 0:
        return {"labels": labels, "revenue": [0] * horizon}

    slope, intercept = np.polyfit(np.arange(history), np.array(values), 1)
    trend_line = [intercept + slope * x for x in range(history)]
    factors = weekday_factors(days, values, trend_line)
    predicted = []
    for k, day in enumerate(future, start=1):
        trend = intercept + slope * (history - 1 + k)
        predicted.append(max(0, int(round(trend * factors[day.weekday()]))))
    return {"labels": labels, "revenue": predicted}