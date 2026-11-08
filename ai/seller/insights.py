"""Gợi ý cho Seller theo luật (mục 10.5, mức 1): mỗi luật khớp thì tạo một gợi ý.

Đầu vào là một dict `ctx` đã được gom sẵn từ database (xem api/services/seller_data.py), nên toàn bộ file là hàm thuần.
"""

# Các ngưỡng, chỉnh tại đây
LOW_STOCK = 5            # sắp hết hàng khi tồn kho từ mức này trở xuống
LOW_STOCK_WINDOW = 14    # ... và có bán trong số ngày này
SLOW_STOCK = 20          # tồn chậm: tồn kho từ mức này trở lên
SLOW_SOLD_MAX = 2        # ... mà bán dưới số này trong 30 ngày
VIEWS_MIN = 100          # nhiều xem: từ số lượt xem này
CONVERSION_MAX = 0.02    # ... mà tỷ lệ mua dưới 2%
TREND_PERCENT = 10       # doanh thu tăng hoặc giảm hơn 10% thì báo
MAX_PER_RULE = 3         # mỗi luật liệt kê tối đa số sản phẩm này

SHAPE_LABELS = {
    "pear": "quả lê", "hourglass": "đồng hồ cát", "rectangle": "chữ nhật",
    "apple": "quả táo", "inverted_triangle": "tam giác ngược",
}
SEVERITY_ORDER = {"warning": 0, "success": 1, "info": 2}


def money(n):
    return f"{int(n):,}".replace(",", ".") + "đ"


def low_stock_items(ctx):
    """Biến thể sắp hết hàng mà vẫn đang bán chạy, ưu tiên cái bán nhiều và còn ít nhất."""
    rows = [v for v in ctx["variants"] if v["stock"] <= LOW_STOCK and v["sold_14d"] > 0]
    return sorted(rows, key=lambda v: (v["stock"], -v["sold_14d"], v["name"]))


def slow_stock_items(ctx):
    rows = [p for p in ctx["products"] if p["stock_total"] >= SLOW_STOCK and p["sold_30d"] < SLOW_SOLD_MAX]
    return sorted(rows, key=lambda p: (-p["stock_total"], p["name"]))


def low_conversion_items(ctx):
    rows = [p for p in ctx["products"]
            if p["views_30d"] >= VIEWS_MIN and p["purchases_30d"] / p["views_30d"] < CONVERSION_MAX]
    return sorted(rows, key=lambda p: (-p["views_30d"], p["name"]))


def best_sellers(ctx):
    rows = [p for p in ctx["products"] if p["sold_30d"] > 0]
    return sorted(rows, key=lambda p: (-p["sold_30d"], p["name"]))[:3]


def revenue_change(ctx):
    """Phần trăm đổi của doanh thu 7 ngày gần nhất so với 7 ngày trước đó, hoặc None nếu không có mốc so sánh."""
    last, prev = ctx["revenue_last7"], ctx["revenue_prev7"]
    if prev <= 0:
        return None if last <= 0 else 100.0
    return (last - prev) / prev * 100


def popular_shape(ctx):
    """Dáng người phổ biến nhất trong số người mua, kèm tỷ lệ. None nếu chưa có dữ liệu."""
    counts = ctx.get("shape_counts") or {}
    total = sum(counts.values())
    if not total:
        return None
    shape = max(sorted(counts), key=lambda s: counts[s])
    return shape, round(counts[shape] / total * 100)


def generate(ctx):
    """Chạy các luật, trả về { summary, suggestions[{ severity, title, detail }] }."""
    suggestions = []

    for v in low_stock_items(ctx)[:MAX_PER_RULE]:
        suggestions.append({
            "severity": "warning", "title": f"Nên nhập thêm {v['name']} (size {v['size']}, màu {v['color']})",
            "detail": f"Chỉ còn {v['stock']} sản phẩm mà đã bán {v['sold_14d']} trong {LOW_STOCK_WINDOW} ngày qua."})

    for p in slow_stock_items(ctx)[:MAX_PER_RULE]:
        suggestions.append({
            "severity": "warning", "title": f"Cân nhắc giảm giá {p['name']}",
            "detail": f"Tồn kho {p['stock_total']} nhưng 30 ngày qua chỉ bán {p['sold_30d']}."})

    for p in low_conversion_items(ctx)[:MAX_PER_RULE]:
        rate = p["purchases_30d"] / p["views_30d"] * 100
        suggestions.append({
            "severity": "info", "title": f"Cải thiện ảnh và mô tả {p['name']}",
            "detail": f"{p['views_30d']} lượt xem nhưng tỷ lệ mua chỉ {rate:.1f}%."})

    change = revenue_change(ctx)
    if change is not None and change > TREND_PERCENT:
        suggestions.append({
            "severity": "success", "title": f"Doanh thu tăng {change:.0f}% so với tuần trước",
            "detail": f"7 ngày gần nhất đạt {money(ctx['revenue_last7'])}, tuần trước đó {money(ctx['revenue_prev7'])}."})
    elif change is not None and change < -TREND_PERCENT:
        suggestions.append({
            "severity": "warning", "title": f"Doanh thu giảm {abs(change):.0f}% so với tuần trước",
            "detail": f"7 ngày gần nhất đạt {money(ctx['revenue_last7'])}, tuần trước đó {money(ctx['revenue_prev7'])}."})

    top = best_sellers(ctx)
    if top:
        names = ", ".join(f"{p['name']} ({p['sold_30d']})" for p in top)
        suggestions.append({
            "severity": "success", "title": "Đẩy mạnh sản phẩm bán chạy và cân nhắc nhập thêm",
            "detail": f"Top bán chạy 30 ngày qua: {names}."})

    shape = popular_shape(ctx)
    if shape:
        key, percent = shape
        suggestions.append({
            "severity": "info", "title": f"Nhập thêm đồ hợp dáng {SHAPE_LABELS.get(key, key)}",
            "detail": f"Dáng {SHAPE_LABELS.get(key, key)} chiếm {percent}% người mua của shop."})

    suggestions.sort(key=lambda s: SEVERITY_ORDER[s["severity"]])   # sort ổn định: giữ thứ tự luật trong cùng mức
    return {"summary": build_summary(ctx, suggestions), "suggestions": suggestions}


def build_summary(ctx, suggestions):
    """Tóm tắt 2 đến 3 câu bằng tiếng Việt, ghép từ các gợi ý nổi bật nhất."""
    sentences = []
    change = revenue_change(ctx)
    if ctx["revenue_last7"] > 0 or ctx["revenue_prev7"] > 0:
        if change is None or abs(change) <= TREND_PERCENT:
            sentences.append(f"Doanh thu 7 ngày qua đạt {money(ctx['revenue_last7'])}, ổn định so với tuần trước.")
        elif change > 0:
            sentences.append(f"Doanh thu 7 ngày qua đạt {money(ctx['revenue_last7'])}, tăng {change:.0f}% so với tuần trước.")
        else:
            sentences.append(f"Doanh thu 7 ngày qua đạt {money(ctx['revenue_last7'])}, giảm {abs(change):.0f}% so với tuần trước.")
    else:
        sentences.append("Chưa có doanh thu trong 14 ngày gần đây.")

    top = best_sellers(ctx)
    if top:
        sentences.append(f"Sản phẩm bán chạy nhất là {top[0]['name']} ({top[0]['sold_30d']} sản phẩm trong 30 ngày).")
    warnings = [s for s in suggestions if s["severity"] == "warning"]
    if warnings:
        sentences.append(f"Có {len(warnings)} việc cần chú ý, ví dụ: {warnings[0]['title']}.")
    else:
        sentences.append("Hiện chưa có vấn đề nào cần xử lý gấp.")
    return " ".join(sentences[:3])