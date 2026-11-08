"""Chatbot cho Buyer (mục 10.6, mức 1): khớp từ khóa với câu hỏi thường gặp và tìm sản phẩm theo tên, tag, danh mục.

Nội dung trả lời nằm trong faq.json để nhóm chỉnh sửa mà không cần đụng vào code.
Mức 2 (gọi LLM) do GPT làm sau, dùng chung hàm answer(message, products).
"""
import json
import os
from functools import lru_cache

from ai.recommender.score import adjacent_pairs, has_phrase, normalize_tokens

FAQ_FILE = os.path.join(os.path.dirname(__file__), "faq.json")
MAX_PRODUCTS = 4
MAX_FAQ_ANSWERS = 2
MIN_WORD = 3

GREETINGS = ("xin chao", "chao", "hello", "hi", "alo")
CATEGORY_WORDS = {
    "ao": ("ao",),
    "quan": ("quan",),
    "vay-dam": ("vay", "dam"),
    "phu-kien": ("phu kien", "tui", "balo", "giay", "kinh", "dong ho", "non"),
}
# Từ quá chung chung, không dùng để khớp tên sản phẩm. Một số từ trùng nhau khi bỏ dấu tiếng Việt:
# "thế" với "thể" (giày thể thao), "đẹp" với "dép". Hạn chế này là cái giá của việc hiểu câu không dấu.
STOP_WORDS = {
    "hang", "san", "pham", "cho", "toi", "minh", "muon", "mua", "tim", "can", "xem", "cua", "nao", "khong",
    "the", "dep", "thoi", "gian", "giao", "nhu", "sao", "duoc", "nhung", "voi", "mot", "cac", "nay", "bao",
    "nhieu", "gia", "tien", "shop",
}

GREETING_REPLY = ("Xin chào! Mình là trợ lý của Fashion. Bạn có thể hỏi về đổi trả, phí và thời gian giao hàng, "
                  "cách chọn size, thanh toán, hoặc tìm sản phẩm (ví dụ: áo thun, váy dài, quần jeans).")
FALLBACK_REPLY = ("Xin lỗi, mình chưa hiểu rõ câu hỏi. Bạn có thể hỏi về đổi trả, phí giao hàng, thời gian giao, "
                  "cách chọn size, thanh toán, hoặc tìm sản phẩm. Cần hỗ trợ thêm thì gửi yêu cầu cho Admin "
                  "(admin@shop.example, hotline 1900 0000).")


@lru_cache(maxsize=1)
def load_faq():
    with open(FAQ_FILE, encoding="utf-8") as f:
        return json.load(f)


def match_faq(tokens):
    """Các câu hỏi thường gặp khớp với câu hỏi, nhiều từ khóa khớp nhất đứng trước (tối đa 2)."""
    scored = []
    for order, item in enumerate(load_faq()):
        hits = sum(1 for kw in item["keywords"] if has_phrase(tokens, kw.split()))
        if hits:
            scored.append((-hits, order, item))
    scored.sort(key=lambda t: (t[0], t[1]))
    return [item for _, _, item in scored[:MAX_FAQ_ANSWERS]]


def match_products(tokens, products, limit=MAX_PRODUCTS):
    """Sản phẩm có tên, tag hoặc danh mục trùng từ khóa trong câu hỏi. Điểm nhiều hơn đứng trước, bằng điểm thì bán chạy hơn."""
    scored = []
    for product in products:
        points = 0
        name_tokens = normalize_tokens(product["name"])
        for word in name_tokens:
            if len(word) >= MIN_WORD and word not in STOP_WORDS and word in tokens:
                points += 2
        points += 2 * adjacent_pairs(tokens, name_tokens)      # "sơ mi" gồm hai từ ngắn nên khớp theo cặp
        for tag in product.get("tags") or ():
            if has_phrase(tokens, tag.replace("-", " ").split()):
                points += 2
        if any(has_phrase(tokens, w.split()) for w in CATEGORY_WORDS.get(product.get("category"), ())):
            points += 1
        if points:
            scored.append((-points, -product.get("sold_count", 0), product["id"]))
    scored.sort()
    return [pid for _, _, pid in scored[:limit]]


def answer(message, products):
    """Trả lời một câu hỏi của người mua. Trả về { reply, product_ids }.

    products: [{ id, name, tags, category, sold_count }] gồm các sản phẩm đang được bán.
    """
    tokens = normalize_tokens(message)
    faqs = match_faq(tokens)
    product_ids = match_products(tokens, products)

    if faqs:
        reply = "\n".join(item["answer"] for item in faqs)
        if product_ids:
            reply += "\nMình gợi ý thêm vài sản phẩm bên dưới nhé."
    elif product_ids:
        reply = f"Mình tìm thấy {len(product_ids)} sản phẩm phù hợp với bạn:"
    elif any(has_phrase(tokens, g.split()) for g in GREETINGS):
        reply = GREETING_REPLY
    else:
        reply = FALLBACK_REPLY
    return {"reply": reply, "product_ids": product_ids}