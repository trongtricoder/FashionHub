"""AI đồng hành cho Seller (mục 10.5, mức 1): khớp từ khóa để chọn ý định, rồi trả lời bằng số liệu thật.

Mức 2 (gọi LLM) do GPT làm sau, cùng giao diện hàm answer(message, ctx).
"""
import unicodedata

from . import insights

STATUS_TEXT = (("pending", "chờ xác nhận"), ("processing", "đang xử lý"), ("shipping", "đang giao"),
               ("completed", "hoàn tất"), ("cancelled", "đã hủy"))

# Thứ tự trong danh sách là thứ tự ưu tiên khi câu hỏi khớp nhiều ý định.
# Cụm từ so khớp theo từ nguyên vẹn (đã bỏ dấu), ví dụ "e" của "hàng ế" không khớp bên trong từ khác.
INTENTS = (
    ("insights", ("goi y", "tu van", "nen lam gi", "phan tich")),
    ("slow", ("e", "cham", "ton lau", "giam gia", "khong ban duoc")),
    ("best", ("ban chay", "top", "tot nhat")),
    ("stock", ("ton kho", "con hang", "het hang", "nhap them", "sap het", "con bao nhieu",
               "trong kho", "so luong ton", "inventory", "in stock")),
    ("revenue", ("doanh thu", "doanh so", "tien ban")),
    ("orders", ("don hang", "don")),
)

STOCK_QUERY_WORDS = {
    "bao", "nhieu", "con", "ton", "kho", "hang", "san", "pham", "trong", "cua", "shop",
    "la", "hien", "tai", "co", "inventory", "stock", "in",
}

HELP = ("Mình chưa hiểu câu hỏi. Bạn có thể hỏi về: doanh thu, tồn kho, sản phẩm bán chạy, "
        "hàng bán chậm, đơn hàng, hoặc xin gợi ý để cải thiện cửa hàng.")


def normalize(text):
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() else " " for c in text).split()


def has_phrase(tokens, phrase):
    """Cụm từ (nhiều từ) có xuất hiện liền nhau trong câu không."""
    words = phrase.split()
    return any(tokens[i:i + len(words)] == words for i in range(len(tokens) - len(words) + 1))


def matching_stock_products(message, products):
    """Chọn sản phẩm có tên khớp với các từ mô tả trong câu hỏi tồn kho."""
    query = set(normalize(message)) - STOCK_QUERY_WORDS
    if not query:
        return []

    matches = []
    minimum_matches = min(2, len(query))
    for product in products:
        name = set(normalize(product["name"]))
        overlap = query & name
        if len(overlap) >= minimum_matches:
            matches.append((-len(overlap), product["name"], product))
    return [product for _, _, product in sorted(matches)]


def detect_intent(message):
    tokens = normalize(message)
    if "don" in tokens and has_phrase(tokens, "con bao nhieu"):
        return "orders"
    for intent, phrases in INTENTS:
        if any(has_phrase(tokens, p) for p in phrases):
            return intent
    return None


def answer(message, ctx):
    """Trả lời một câu hỏi của Seller. Trả về chuỗi tiếng Việt."""
    intent = detect_intent(message)
    if intent == "revenue":
        return (f"Doanh thu 7 ngày gần nhất: {insights.money(ctx['revenue_last7'])}. "
                f"Doanh thu 30 ngày gần nhất: {insights.money(ctx['revenue_30d'])}.")

    if intent == "stock":
        matched_products = matching_stock_products(message, ctx["products"])
        if matched_products:
            details = []
            for product in matched_products[:5]:
                variants = [v for v in ctx["variants"] if v["product_id"] == product["id"]]
                variant_text = "; ".join(
                    f"{v['size']}, {v['color']}: {v['stock']}" for v in variants[:5]
                )
                detail = f"{product['name']}: còn {product['stock_total']}"
                if variant_text:
                    detail += f" ({variant_text})"
                details.append(detail)
            return "Tồn kho theo sản phẩm: " + "; ".join(details) + "."

        low = insights.low_stock_items(ctx)
        text = f"Tổng tồn kho của shop: {ctx['total_stock']} sản phẩm."
        if low:
            items = "; ".join(f"{v['name']} ({v['size']}, {v['color']}): còn {v['stock']}" for v in low[:5])
            text += f" Sắp hết hàng và đang bán chạy: {items}."
        else:
            text += " Chưa có mặt hàng nào vừa sắp hết vừa đang bán chạy."
        return text

    if intent == "best":
        top = insights.best_sellers(ctx)
        if not top:
            return "30 ngày qua shop chưa bán được sản phẩm nào."
        return "Top bán chạy 30 ngày qua: " + "; ".join(f"{i}. {p['name']} ({p['sold_30d']})" for i, p in enumerate(top, 1)) + "."

    if intent == "slow":
        slow = insights.slow_stock_items(ctx)
        if not slow:
            return "Hiện không có sản phẩm nào tồn kho nhiều mà bán chậm."
        items = "; ".join(f"{p['name']} (tồn {p['stock_total']}, bán {p['sold_30d']})" for p in slow[:5])
        return f"Hàng tồn chậm, nên cân nhắc giảm giá: {items}."

    if intent == "orders":
        counts = ctx["orders_by_status"]
        return "Đơn hàng của shop: " + ", ".join(f"{counts.get(key, 0)} {label}" for key, label in STATUS_TEXT) + "."

    if intent == "insights":
        result = insights.generate(ctx)
        lines = [result["summary"]] + [f"- {s['title']}: {s['detail']}" for s in result["suggestions"][:4]]
        return "\n".join(lines)

    return HELP