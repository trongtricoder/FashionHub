"""Gợi ý sản phẩm theo công thức điểm tổng hợp (mục 10.2, mức 1).

    score = 100 * (0.30 * fit_size + 0.25 * fit_style + 0.20 * fit_budget + 0.15 * rating_norm + 0.10 * popularity_norm)

Mọi hàm đều thuần (không gọi database) nên test và giải thích được từng thành phần điểm.
"""
import unicodedata

from . import size_chart

WEIGHTS = {"size": 0.30, "style": 0.25, "budget": 0.20, "rating": 0.15, "popularity": 0.10}
WISH_BONUS = 5            # cộng thêm khi mong muốn của người mua khớp tag hoặc tên sản phẩm
NO_REVIEW_RATING = 0.6    # chưa có đánh giá thì coi như 0.6
REASON_THRESHOLD = 0.7    # thành phần từ mức này trở lên được nêu thành lý do
MAX_REASONS = 3
MAX_PER_SHOP = 3          # mỗi shop tối đa số sản phẩm này trong kết quả
MIN_WISH_WORD = 3         # từ trong tên sản phẩm phải dài từ số ký tự này mới dùng để khớp mong muốn

SHAPE_LABELS = {
    "pear": "quả lê", "hourglass": "đồng hồ cát", "rectangle": "chữ nhật",
    "apple": "quả táo", "inverted_triangle": "tam giác ngược",
}
TAG_LABELS = {
    "toi-gian": "tối giản", "basic": "cơ bản", "streetwear": "đường phố", "nang-dong": "năng động",
    "cong-so": "công sở", "the-thao": "thể thao", "nu-tinh": "nữ tính", "vintage": "cổ điển",
    "mua-dong": "mùa đông", "mua-he": "mùa hè", "cao-cap": "cao cấp",
}


def normalize_tokens(text):
    """Chữ thường, bỏ dấu, tách thành các từ."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return "".join(c if c.isalnum() else " " for c in text).split()


def has_phrase(tokens, phrase_tokens):
    n = len(phrase_tokens)
    return bool(n) and any(tokens[i:i + n] == phrase_tokens for i in range(len(tokens) - n + 1))


# ---------- các thành phần điểm (mỗi thành phần từ 0 đến 1) ----------

def size_ok(recommended, sizes):
    """1 nếu có size đúng còn hàng, 0.5 nếu sai một bậc, 0 nếu xa hơn. Hàng không chia size (Free) thì 0.5 trung tính."""
    ranks = [r for r in (size_chart.rank(s) for s in sizes) if r is not None]
    target = size_chart.rank(recommended)
    if target is None or not ranks:
        return 0.5
    if target in ranks:
        return 1.0
    return 0.5 if any(abs(r - target) == 1 for r in ranks) else 0.0


def shape_ok(body_shape, suits_shapes):
    """1 nếu dáng người nằm trong danh sách phù hợp. Sản phẩm không ghi dáng phù hợp thì 0.5."""
    if not suits_shapes or not body_shape:
        return 0.5
    return 1.0 if body_shape in suits_shapes else 0.0


def fit_size(profile, candidate):
    recommended = size_chart.recommend_size(profile.get("height_cm"), profile.get("weight_kg"))
    s = size_ok(recommended, candidate["sizes"])
    h = shape_ok(profile.get("body_shape"), candidate.get("suits_shapes"))
    return 0.6 * s + 0.4 * h, recommended, s, h


def fit_style(style_tags, product_tags):
    """Độ giống (Jaccard) giữa phong cách của người mua và tag sản phẩm. Người mua chưa chọn phong cách thì 0.5."""
    wanted, tags = set(style_tags or ()), set(product_tags or ())
    if not wanted:
        return 0.5
    union = wanted | tags
    return len(wanted & tags) / len(union) if union else 0.5


def fit_budget(price, budget_max):
    """1 nếu trong ngân sách, vượt thì giảm dần về 0. Không có ngân sách thì 1."""
    if not budget_max:
        return 1.0
    if price <= budget_max:
        return 1.0
    return max(0.0, 1 - (price - budget_max) / budget_max)


def rating_norm(avg, count):
    return NO_REVIEW_RATING if not count else avg / 5


def popularity_norm(sold, max_sold):
    return min(1.0, sold / max_sold) if max_sold > 0 else 0.0


def adjacent_pairs(tokens, name_tokens):
    """Số cặp từ liền nhau trong tên sản phẩm cũng liền nhau trong câu. Giúp khớp tên có từ ngắn như "sơ mi"."""
    return sum(1 for i in range(len(name_tokens) - 1) if has_phrase(tokens, name_tokens[i:i + 2]))


def wish_matches(wishes_text, candidate):
    """Mong muốn của người mua (văn bản tự do) có nhắc tới tag hoặc tên sản phẩm không. Trả về True/False."""
    tokens = normalize_tokens(wishes_text)
    if not tokens:
        return False
    for tag in candidate.get("tags") or ():
        if has_phrase(tokens, tag.replace("-", " ").split()):
            return True
    name_tokens = normalize_tokens(candidate["name"])
    if any(w in tokens for w in name_tokens if len(w) >= MIN_WISH_WORD):
        return True
    return adjacent_pairs(tokens, name_tokens) > 0


# ---------- tổng hợp ----------

def score_candidate(profile, candidate, max_sold, wishes_text=""):
    """Tính điểm và lý do cho một sản phẩm. Trả về { id, score, reasons, parts }."""
    size_part, recommended, size_flag, shape_flag = fit_size(profile, candidate)
    parts = {
        "size": size_part,
        "style": fit_style(profile.get("style_tags"), candidate.get("tags")),
        "budget": fit_budget(candidate["price"], profile.get("budget_max")),
        "rating": rating_norm(candidate.get("rating_avg", 0), candidate.get("rating_count", 0)),
        "popularity": popularity_norm(candidate.get("sold_count", 0), max_sold),
    }
    base = 100 * sum(WEIGHTS[k] * parts[k] for k in WEIGHTS)
    wished = wish_matches(wishes_text, candidate)
    total = min(100.0, base + (WISH_BONUS if wished else 0))

    reasons = []
    if wished:
        reasons.append("Đúng mong muốn của bạn")
    if parts["size"] >= REASON_THRESHOLD:
        if size_flag == 1.0:
            reasons.append(f"Hợp size {recommended} theo số đo của bạn")
        elif shape_flag == 1.0:
            reasons.append(f"Hợp dáng người {SHAPE_LABELS.get(profile.get('body_shape'), '')}".strip())
    if parts["style"] >= REASON_THRESHOLD and profile.get("style_tags"):
        common = [TAG_LABELS.get(t, t) for t in profile["style_tags"] if t in (candidate.get("tags") or ())]
        reasons.append("Hợp phong cách " + ", ".join(common) if common else "Hợp phong cách của bạn")
    if parts["budget"] >= REASON_THRESHOLD and profile.get("budget_max"):
        reasons.append("Nằm trong ngân sách" if candidate["price"] <= profile["budget_max"] else "Gần mức ngân sách của bạn")
    if parts["rating"] >= REASON_THRESHOLD and candidate.get("rating_count"):
        reasons.append("Được đánh giá cao")
    if parts["popularity"] >= REASON_THRESHOLD:
        reasons.append("Nhiều người mua")
    return {"id": candidate["id"], "score": round(total, 1), "reasons": reasons[:MAX_REASONS], "parts": parts}


def recommend(profile, candidates, limit=8, extra_wishes=""):
    """Chấm điểm mọi sản phẩm ứng viên rồi chọn `limit` sản phẩm điểm cao nhất, mỗi shop tối đa 3.

    candidates: [{ id, shop_id, name, price, tags, suits_shapes, sold_count, rating_avg, rating_count, sizes }]
    (chỉ gồm sản phẩm đã duyệt và còn hàng; `sizes` là các size còn tồn kho).
    """
    if not candidates:
        return []
    max_sold = max(c.get("sold_count", 0) for c in candidates)
    wishes_text = f"{profile.get('wishes') or ''} {extra_wishes or ''}"
    scored = [(score_candidate(profile, c, max_sold, wishes_text), c) for c in candidates]
    scored.sort(key=lambda pair: (-pair[0]["score"], -pair[1].get("sold_count", 0), pair[1]["id"]))

    per_shop, result = {}, []
    for item, candidate in scored:
        shop = candidate["shop_id"]
        if per_shop.get(shop, 0) >= MAX_PER_SHOP:
            continue
        per_shop[shop] = per_shop.get(shop, 0) + 1
        result.append(item)
        if len(result) >= limit:
            break
    return result