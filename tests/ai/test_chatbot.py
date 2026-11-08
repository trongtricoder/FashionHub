"""Test chatbot cho Buyer (mục 10.6): câu hỏi thường gặp, tìm sản phẩm, chào hỏi, câu không hiểu."""
import pytest

from ai.chatbot import bot
from ai.recommender.score import normalize_tokens

PRODUCTS = [
    {"id": 1, "name": "Áo thun basic", "tags": ["basic", "toi-gian"], "category": "ao", "sold_count": 9},
    {"id": 2, "name": "Áo sơ mi", "tags": ["cong-so"], "category": "ao", "sold_count": 4},
    {"id": 3, "name": "Váy dài", "tags": ["nu-tinh", "vintage"], "category": "vay-dam", "sold_count": 2},
    {"id": 4, "name": "Quần jeans", "tags": ["basic"], "category": "quan", "sold_count": 7},
    {"id": 5, "name": "Túi tote", "tags": ["toi-gian"], "category": "phu-kien", "sold_count": 1},
    {"id": 6, "name": "Giày thể thao", "tags": ["the-thao"], "category": "phu-kien", "sold_count": 3},
]


def ids(message):
    return bot.answer(message, PRODUCTS)["product_ids"]


def reply(message):
    return bot.answer(message, PRODUCTS)["reply"]


# ---------- câu hỏi thường gặp ----------

@pytest.mark.parametrize("message,expected", [
    ("Shop đổi trả như thế nào?", "trả hàng"),
    ("phí ship bao nhiêu vậy", "chưa thu phí giao hàng"),
    ("giao hàng bao lâu thì nhận được", "Thời gian giao dự kiến"),
    ("mình cao 1m65 mặc size nào", "bậc lớn hơn"),
    ("có thanh toán COD không", "COD"),
    ("cho mình số hotline admin", "1900 0000"),
])
def test_tra_loi_cau_hoi_thuong_gap(message, expected):
    assert expected in reply(message)


def test_tra_loi_size_khop_voi_bang_size_that():
    text = reply("cách chọn size")
    assert "160 cm" in text and "168 cm" in text and "52 kg" in text and "85 kg" in text


def test_hoi_hai_chu_de_thi_tra_loi_ca_hai_toi_da_2():
    text = reply("phí ship và thời gian giao hàng thế nào")
    assert "chưa thu phí" in text and "Thời gian giao dự kiến" in text
    assert text.count("\n") == 1                                       # đúng 2 câu trả lời


def test_khong_dau_va_viet_hoa_van_hieu():
    assert "COD" in reply("THANH TOAN the nao")


# ---------- tìm sản phẩm ----------

def test_tim_theo_ten_san_pham_va_bo_tu_chung_chung():
    assert ids("tôi muốn mua áo thun") == [1, 2]          # "thun" khớp áo thun (2 điểm) + cùng danh mục áo (1 điểm); áo sơ mi chỉ có danh mục
    assert ids("tìm váy dài") == [3]
    assert ids("hàng nào đẹp") == []                      # "hàng", "đẹp" (trùng "dép" khi bỏ dấu) là từ chung chung
    assert ids("giao hàng thế nào") == []                 # "thế" không bị nhầm với "thể" trong "giày thể thao"


def test_ten_co_tu_ngan_van_khop_theo_cap_tu():
    assert ids("tìm áo sơ mi") == [2, 1]        # "sơ mi" chỉ gồm từ 2 ký tự, khớp nhờ cặp từ liền nhau; áo thun chỉ khớp danh mục


def test_tim_theo_tag_va_danh_muc():
    assert ids("mình thích phong cách tối giản") == [1, 5]       # cùng tag toi-gian, bán chạy hơn đứng trước
    assert ids("có phụ kiện gì không") == [6, 5]
    assert ids("cho xem quần") == [4]


def test_toi_da_4_san_pham_xep_theo_diem_roi_ban_chay():
    many = [{"id": i, "name": f"Áo mẫu {i}", "tags": [], "category": "ao", "sold_count": i} for i in range(1, 9)]
    assert bot.answer("xem áo", many)["product_ids"] == [8, 7, 6, 5]


def test_hoi_dap_co_ca_san_pham_thi_noi_se_goi_y_them():
    result = bot.answer("đổi trả áo thun được không", PRODUCTS)
    assert "trả hàng" in result["reply"] and "gợi ý thêm" in result["reply"] and 1 in result["product_ids"]


def test_chi_co_san_pham_thi_cau_dan():
    assert reply("áo thun").startswith("Mình tìm thấy")


# ---------- chào hỏi và không hiểu ----------

def test_chao_hoi_va_khong_hieu():
    assert reply("xin chào").startswith("Xin chào") and ids("xin chào") == []
    assert reply("asdfgh qwerty") == bot.FALLBACK_REPLY and "admin@shop.example" in bot.FALLBACK_REPLY


def test_chu_hi_khong_bi_nham_trong_tu_khac():
    assert reply("this is a long text") == bot.FALLBACK_REPLY      # "hi" chỉ khớp khi là từ nguyên vẹn


# ---------- dữ liệu câu hỏi thường gặp ----------

def test_faq_hop_le():
    faq = bot.load_faq()
    assert len({item["id"] for item in faq}) == len(faq) and len(faq) >= 6
    for item in faq:
        assert item["answer"].strip() and item["keywords"]
        for keyword in item["keywords"]:
            assert keyword == " ".join(normalize_tokens(keyword)), f"từ khóa chưa chuẩn hóa (không dấu, chữ thường): {keyword}"