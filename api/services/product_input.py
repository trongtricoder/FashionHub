"""Kiểm tra và làm sạch dữ liệu sản phẩm và shop do Seller gửi lên (mục 10.7: kiểm tra độ dài, kiểu, khoảng giá trị)."""
import re
import unicodedata

CATEGORIES = ("ao", "quan", "vay-dam", "phu-kien")
SHAPES = ("pear", "hourglass", "rectangle", "apple", "inverted_triangle")
MODEL_GENDERS = ("female", "male")

MAX_VARIANTS = 30
MAX_IMAGES = 8
MAX_TAGS = 10
MAX_PRICE = 2_000_000_000
MAX_STOCK = 100_000


class InputError(Exception):
    """Dữ liệu gửi lên không hợp lệ; message bằng tiếng Việt để hiện thẳng cho người dùng."""


def _text(value, label, max_len, required=False):
    """Chuỗi đã cắt khoảng trắng, kiểm tra độ dài."""
    if value is not None and not isinstance(value, str):
        raise InputError(f"{label} phải là chữ.")
    value = (value or "").strip()
    if required and not value:
        raise InputError(f"Vui lòng nhập {label.lower()}.")
    if len(value) > max_len:
        raise InputError(f"{label} tối đa {max_len} ký tự.")
    return value


def _int(value, label, low, high):
    """Số nguyên trong khoảng [low, high]. Không nhận True/False và số thực lẫn trong."""
    if isinstance(value, bool) or not isinstance(value, int):
        if isinstance(value, str) and re.fullmatch(r"-?\d+", value.strip()):
            value = int(value)
        else:
            raise InputError(f"{label} phải là số nguyên.")
    if not low <= value <= high:
        raise InputError(f"{label} phải từ {low} đến {high}.")
    return value


def _url(value, label):
    """Đường dẫn http hoặc https, hoặc None nếu để trống."""
    value = _text(value, label, 500)
    if not value:
        return None
    if not value.startswith(("http://", "https://")):
        raise InputError(f"{label} phải là đường dẫn http hoặc https.")
    return value


def slugify(text):
    """Đổi 'Tối giản' thành 'toi-gian' để khớp với style_tags của người mua."""
    text = unicodedata.normalize("NFD", text.lower().replace("đ", "d"))
    text = "".join(c for c in text if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", "-", text).strip("-")


def parse_product(body):
    """Làm sạch dữ liệu sản phẩm. Trả về dict đã chuẩn hóa hoặc ném InputError."""
    category = body.get("category")
    if category not in CATEGORIES:
        raise InputError("Danh mục không hợp lệ.")

    raw_tags = body.get("tags") or []
    if not isinstance(raw_tags, list):
        raise InputError("Tag phải là một danh sách.")
    tags = []
    for tag in raw_tags:
        slug = slugify(_text(tag, "Tag", 30))
        if slug and slug not in tags:
            tags.append(slug)
    if len(tags) > MAX_TAGS:
        raise InputError(f"Tối đa {MAX_TAGS} tag.")

    shapes = body.get("suits_shapes") or []
    if not isinstance(shapes, list) or any(s not in SHAPES for s in shapes):
        raise InputError("Dáng người phù hợp không hợp lệ.")

    raw_variants = body.get("variants")
    if not isinstance(raw_variants, list) or not raw_variants:
        raise InputError("Cần ít nhất một phân loại (size, màu, tồn kho).")
    if len(raw_variants) > MAX_VARIANTS:
        raise InputError(f"Tối đa {MAX_VARIANTS} phân loại.")
    variants, seen = [], set()
    for item in raw_variants:
        if not isinstance(item, dict):
            raise InputError("Phân loại không hợp lệ.")
        size = _text(item.get("size"), "Size", 10, required=True).upper()
        color = _text(item.get("color"), "Màu", 30, required=True)
        key = (size.lower(), color.lower())
        if key in seen:
            raise InputError(f"Phân loại {size} / {color} bị trùng.")
        seen.add(key)
        variants.append({"size": size, "color": color, "stock": _int(item.get("stock", 0), "Tồn kho", 0, MAX_STOCK)})

    raw_images = body.get("images") or []
    if not isinstance(raw_images, list) or len(raw_images) > MAX_IMAGES:
        raise InputError(f"Tối đa {MAX_IMAGES} ảnh.")
    images = []
    for item in raw_images:
        url = _url(item.get("url") if isinstance(item, dict) else None, "Đường dẫn ảnh")
        if not url:
            raise InputError("Có ảnh thiếu đường dẫn.")
        images.append({"url": url, "is_main": bool(item.get("is_main"))})
    if images:
        main = next((i for i, img in enumerate(images) if img["is_main"]), 0)
        for i, img in enumerate(images):
            img["is_main"] = (i == main)

    return {
        "name": _text(body.get("name"), "Tên sản phẩm", 120, required=True),
        "description": _text(body.get("description"), "Mô tả", 2000),
        "price": _int(body.get("price"), "Giá", 0, MAX_PRICE),
        "category": category,
        "tags": tags,
        "suits_shapes": list(dict.fromkeys(shapes)),
        "variants": variants,
        "images": images,
        "tryon_layer_url": _url(body.get("tryon_layer_url"), "Ảnh lớp thử đồ"),
    }


def parse_shop(body):
    """Làm sạch thông tin shop. Tọa độ phải có đủ cả lat và lng hoặc bỏ trống cả hai."""
    lat, lng = body.get("lat"), body.get("lng")
    if (lat is None) != (lng is None):
        raise InputError("Vị trí cần có đủ cả vĩ độ và kinh độ.")
    if lat is not None:
        try:
            lat, lng = float(lat), float(lng)
        except (TypeError, ValueError):
            raise InputError("Vị trí không hợp lệ.")
        if not (-90 <= lat <= 90 and -180 <= lng <= 180):
            raise InputError("Vị trí nằm ngoài phạm vi cho phép.")
    return {
        "name": _text(body.get("name"), "Tên shop", 100, required=True),
        "description": _text(body.get("description"), "Mô tả shop", 500),
        "address": _text(body.get("address"), "Địa chỉ", 255),
        "lat": lat,
        "lng": lng,
        "prep_minutes": _int(body.get("prep_minutes", 60), "Thời gian chuẩn bị hàng (phút)", 5, 600),
    }


def parse_body_profile(body):
    """Làm sạch số đo cá nhân của người mua (mục 9.1). Chiều cao, cân nặng, dáng người là bắt buộc."""
    shape = body.get("body_shape")
    if shape not in SHAPES:
        raise InputError("Vui lòng chọn dáng người.")
    model_gender = body.get("model_gender", "female")
    if model_gender not in MODEL_GENDERS:
        raise InputError("Kiểu người mẫu không hợp lệ.")

    raw_tags = body.get("style_tags") or []
    if not isinstance(raw_tags, list):
        raise InputError("Phong cách phải là một danh sách.")
    tags = []
    for tag in raw_tags:
        slug = slugify(_text(tag, "Phong cách", 30))
        if slug and slug not in tags:
            tags.append(slug)
    if len(tags) > MAX_TAGS:
        raise InputError(f"Tối đa {MAX_TAGS} phong cách.")

    budget = body.get("budget_max")
    return {
        "height_cm": _int(body.get("height_cm"), "Chiều cao (cm)", 100, 230),
        "weight_kg": _int(body.get("weight_kg"), "Cân nặng (kg)", 25, 200),
        "model_gender": model_gender,
        "body_shape": shape,
        "style_tags": tags,
        "budget_max": None if budget in (None, "") else _int(budget, "Ngân sách", 0, 100_000_000),
        "wishes": _text(body.get("wishes"), "Mong muốn", 300),
    }