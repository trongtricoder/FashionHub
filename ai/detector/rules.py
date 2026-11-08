"""Luật cứng của AI Detector (mục 10.3 của PROJECT_CONTEXT).

Mọi ngưỡng và số điểm nằm ở đầu file để nhóm chỉnh mà không phải đọc code bên dưới.
Mỗi luật nhận dữ liệu thô và trả về một "lý do" { rule, points, detail } hoặc None nếu không vi phạm.
"""
import json
import os
import re
import unicodedata
from functools import lru_cache

# ---------- Ngưỡng quyết định ----------
APPROVE_MAX = 29      # 0 đến 29: duyệt ngay
PENDING_MAX = 69      # 30 đến 69: chờ Admin duyệt; từ 70 trở lên: chặn
MAX_SCORE = 100

# ---------- Điểm của từng luật ----------
BANNED_KEYWORD_POINTS = 40   # mỗi từ khóa khác nhau
BANNED_KEYWORD_CAP = 70      # tối đa cho luật này
EXTERNAL_CONTACT_POINTS = 25
PRICE_MIN = 10_000
PRICE_MAX = 20_000_000
PRICE_ANOMALY_POINTS = 25
NO_IMAGE_POINTS = 20
SHORT_DESCRIPTION_MIN = 20   # mô tả ngắn hơn số ký tự này bị cộng điểm
SHORT_DESCRIPTION_POINTS = 10
SPAM_POINTS = 10
SPAM_REPEAT = 6              # ký tự lặp liên tiếp từ 6 lần
SPAM_CAPS_OVER = 12          # tên viết hoa toàn bộ dài hơn 12 ký tự
DUPLICATE_POINTS = 30
MISSING_ADDRESS_POINTS = 10

# ---------- Xử lý tài khoản (xem moderation.py) ----------
WARNING_WINDOW_DAYS = 7      # đếm số mục bị chặn trong ngần ấy ngày
BAN_AFTER_BLOCKED = 3        # từ 3 mục bị chặn trở lên thì khóa tài khoản

KEYWORDS_FILE = os.path.join(os.path.dirname(__file__), "banned_keywords.json")

PHONE_RE = re.compile(r"(?<!\d)(\+84|0)\d{9,10}(?!\d)")
LINK_RE = re.compile(r"https?://|www\.|bit\.ly|t\.me|facebook\.com")
# Ký tự lặp: bỏ qua khoảng trắng và chữ số (giá "1000000" có 6 số 0 liền nhau không phải spam)
REPEAT_RE = re.compile(r"([^\s\d])\1{%d,}" % (SPAM_REPEAT - 1))


def normalize(text):
    """Chữ thường, bỏ dấu tiếng Việt, để so khớp không phân biệt hoa thường và dấu."""
    text = unicodedata.normalize("NFD", (text or "").lower().replace("đ", "d"))
    return "".join(c for c in text if unicodedata.category(c) != "Mn")


@lru_cache(maxsize=1)
def load_keywords():
    """Đọc danh sách từ khóa cấm. Trả về danh sách (từ gốc, từ đã chuẩn hóa)."""
    with open(KEYWORDS_FILE, encoding="utf-8") as f:
        words = json.load(f)
    return [(w, normalize(w)) for w in words]


def rule_banned_keyword(name, description):
    """Tên hoặc mô tả chứa từ khóa cấm. Khớp theo từ nguyên vẹn nên size XXXL không bị nhầm với "xxx"."""
    text = normalize(f"{name} {description}")
    found = [
        original for original, norm in load_keywords()
        if re.search(r"(?<!\w)" + re.escape(norm) + r"(?!\w)", text)
    ]
    if not found:
        return None
    points = min(BANNED_KEYWORD_POINTS * len(found), BANNED_KEYWORD_CAP)
    return {"rule": "banned_keyword", "points": points, "detail": "Chứa từ khóa cấm: " + ", ".join(found)}


def rule_external_contact(name, description):
    """Có số điện thoại, Zalo hoặc đường link dẫn ra ngoài (lách việc mua bán trên hệ thống)."""
    raw = f"{name} {description}"
    # Gộp số bị tách bằng dấu cách, chấm, gạch: "0901 234 567" thành "0901234567"
    digits_joined = re.sub(r"(?<=\d)[ .\-](?=\d)", "", raw)
    kinds = []
    if PHONE_RE.search(digits_joined):
        kinds.append("số điện thoại")
    if "zalo" in normalize(raw):
        kinds.append("Zalo")
    if LINK_RE.search(raw.lower()):
        kinds.append("đường link ngoài")
    if not kinds:
        return None
    return {"rule": "external_contact", "points": EXTERNAL_CONTACT_POINTS, "detail": "Có " + ", ".join(kinds)}


def rule_price_anomaly(price):
    """Giá thấp hoặc cao bất thường (chỉ áp dụng cho sản phẩm)."""
    if price is None or PRICE_MIN <= price <= PRICE_MAX:
        return None
    side = "thấp" if price < PRICE_MIN else "cao"
    return {"rule": "price_anomaly", "points": PRICE_ANOMALY_POINTS,
            "detail": f"Giá {price:,}đ {side} bất thường".replace(",", ".")}


def rule_no_image(image_count):
    """Sản phẩm không có ảnh nào."""
    if image_count is None or image_count > 0:
        return None
    return {"rule": "no_image", "points": NO_IMAGE_POINTS, "detail": "Sản phẩm không có ảnh"}


def rule_short_description(description):
    """Mô tả quá ngắn."""
    if len((description or "").strip()) >= SHORT_DESCRIPTION_MIN:
        return None
    return {"rule": "short_description", "points": SHORT_DESCRIPTION_POINTS,
            "detail": f"Mô tả ngắn hơn {SHORT_DESCRIPTION_MIN} ký tự"}


def rule_spam_text(name, description):
    """Ký tự lặp liên tiếp, hoặc tên viết hoa toàn bộ và dài."""
    problems = []
    if REPEAT_RE.search(f"{name} {description}"):
        problems.append(f"ký tự lặp từ {SPAM_REPEAT} lần liên tiếp")
    clean_name = (name or "").strip()
    if len(clean_name) > SPAM_CAPS_OVER and clean_name.isupper():
        problems.append("tên viết hoa toàn bộ")
    if not problems:
        return None
    return {"rule": "spam_text", "points": SPAM_POINTS, "detail": "Nghi ngờ spam: " + ", ".join(problems)}


def rule_duplicate(name, duplicate_names):
    """Trùng tên (sau khi chuẩn hóa) với sản phẩm của shop khác."""
    if normalize(name).strip() in set(duplicate_names or ()):
        return {"rule": "duplicate", "points": DUPLICATE_POINTS, "detail": "Trùng tên với sản phẩm của shop khác"}
    return None


def rule_missing_address(address):
    """Shop thiếu địa chỉ."""
    if (address or "").strip():
        return None
    return {"rule": "missing_address", "points": MISSING_ADDRESS_POINTS, "detail": "Shop chưa có địa chỉ"}


def decide(score):
    """Đổi điểm rủi ro thành quyết định: approved, pending hoặc blocked."""
    if score <= APPROVE_MAX:
        return "approved"
    if score <= PENDING_MAX:
        return "pending"
    return "blocked"