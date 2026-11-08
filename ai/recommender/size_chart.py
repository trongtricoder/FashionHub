"""Bảng size gợi ý theo số đo (mục 10.2): lấy bậc lớn hơn của hai bậc theo chiều cao và theo cân nặng."""

SIZES = ("S", "M", "L", "XL", "XXL")

# (size, mức tối đa). Vượt hết các mức thì là XXL
HEIGHT_MAX_CM = (("S", 160), ("M", 168), ("L", 176), ("XL", 184))
WEIGHT_MAX_KG = (("S", 52), ("M", 62), ("L", 72), ("XL", 85))


def _size_by(value, table):
    for size, limit in table:
        if value <= limit:
            return size
    return "XXL"


def rank(size):
    """Thứ tự của size (S = 0 ... XXL = 4), hoặc None nếu không phải size quần áo (ví dụ Free)."""
    size = (size or "").strip().upper()
    return SIZES.index(size) if size in SIZES else None


def recommend_size(height_cm, weight_kg):
    """Size gợi ý. Thiếu số đo thì trả về None."""
    if not height_cm or not weight_kg:
        return None
    by_height, by_weight = _size_by(height_cm, HEIGHT_MAX_CM), _size_by(weight_kg, WEIGHT_MAX_KG)
    return by_height if rank(by_height) >= rank(by_weight) else by_weight