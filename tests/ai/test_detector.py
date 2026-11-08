"""Test AI Detector mức 1 (mục 10.3): từng luật, ngưỡng quyết định, và 4 sản phẩm vi phạm trong seed.sql."""
import pytest

from ai.detector import detect, rules

GOOD = "Áo thun cotton 100% mềm mịn, thấm hút tốt, dễ phối đồ mỗi ngày."


def product(**kw):
    data = {"name": "Áo thun basic", "description": GOOD, "price": 150000, "image_count": 2, "duplicate_names": set()}
    data.update(kw)
    return detect.score("product", data)


def rule_names(result):
    return [r["rule"] for r in result["reasons"]]


def test_san_pham_binh_thuong_duoc_duyet():
    result = product()
    assert result == {"risk_score": 0, "decision": "approved", "reasons": []}


def test_tu_khoa_cam_khong_phan_biet_hoa_thuong_va_dau():
    assert rule_names(product(name="Áo HÀNG NHÁI cao cấp")) == ["banned_keyword"]
    assert rule_names(product(name="Ao hang nhai gia re")) == ["banned_keyword"]   # bỏ dấu vẫn bị bắt


def test_tu_khoa_cam_cong_40_moi_tu_toi_da_70():
    one = product(name="Áo replica")["reasons"][0]
    assert one["points"] == 40
    many = product(name="Áo replica fake", description=GOOD + " hàng nhái like auth")["reasons"][0]
    assert many["points"] == 70


def test_size_xxxl_khong_bi_nham_voi_tu_khoa_xxx():
    assert product(description=GOOD + " Có đủ size S M L XL XXL XXXL")["decision"] == "approved"


@pytest.mark.parametrize("text", [
    "Liên hệ 0901234567 để đặt", "gọi 0901 234 567", "ib zalo shop", "xem tại https://shop.vn",
    "mua ở bit.ly/abc", "kênh t.me/shop", "facebook.com/shop",
])
def test_lien_he_ngoai_he_thong(text):
    assert "external_contact" in rule_names(product(description=GOOD + " " + text))


def test_gia_tien_khong_bi_nham_thanh_so_dien_thoai():
    assert "external_contact" not in rule_names(product(description=GOOD + " Giá 1.500.000 hoặc 100000000"))


@pytest.mark.parametrize("price,expected", [(5000, True), (9999, True), (10000, False), (20_000_000, False), (20_000_001, True)])
def test_gia_bat_thuong(price, expected):
    assert ("price_anomaly" in rule_names(product(price=price))) is expected


def test_thieu_anh_va_mo_ta_ngan():
    names = rule_names(product(image_count=0, description="Áo đẹp"))
    assert "no_image" in names and "short_description" in names


def test_spam_ky_tu_lap_va_ten_viet_hoa():
    assert "spam_text" in rule_names(product(description=GOOD + " siêu rẻ!!!!!!"))
    assert "spam_text" in rule_names(product(name="ÁO THUN SIÊU RẺ HÔM NAY"))
    assert "spam_text" not in rule_names(product(name="ÁO THUN"))                       # viết hoa nhưng ngắn
    assert "spam_text" not in rule_names(product(description=GOOD + " giá 1000000"))     # nhiều số 0 liền nhau


def test_trung_ten_voi_shop_khac():
    dupes = {rules.normalize("Váy dài")}
    assert "duplicate" in rule_names(product(name="VÁY  dài".replace("  ", " "), duplicate_names=dupes))
    assert "duplicate" not in rule_names(product(name="Váy ngắn", duplicate_names=dupes))


def test_nguong_quyet_dinh():
    assert rules.decide(0) == rules.decide(29) == "approved"
    assert rules.decide(30) == rules.decide(69) == "pending"
    assert rules.decide(70) == rules.decide(100) == "blocked"


def test_diem_bi_gioi_han_o_100():
    result = product(name="Rolex fake replica", description="hàng nhái zalo 0901234567 !!!!!!", price=1, image_count=0)
    assert result["risk_score"] == 100 and result["decision"] == "blocked"


# ---- Đúng 4 sản phẩm vi phạm trong database/seed.sql ----

def test_seed_ao_gucci_replica_bi_chan_95():
    result = product(name="Áo Gucci replica like auth", description="Hàng nhái cao cấp giá rẻ, liên hệ zalo 0901234567 để đặt.",
                     price=99000, image_count=1)
    assert (result["risk_score"], result["decision"]) == (95, "blocked")
    assert rule_names(result) == ["banned_keyword", "external_contact"]


def test_seed_dong_ho_rolex_fake_bi_chan_95():
    result = product(name="Đồng hồ Rolex fake", description="Fake 1:1", price=5000, image_count=0)
    assert (result["risk_score"], result["decision"]) == (95, "blocked")


def test_seed_ao_thun_sieu_re_cho_duyet_55():
    result = product(name="ÁO THUN SIÊU RẺ SIÊU RẺ SIÊU RẺ", description="Áo thun cotton rẻ nhất thị trường!!!!!!",
                     price=8000, image_count=0)
    assert (result["risk_score"], result["decision"]) == (55, "pending")
    assert sorted(rule_names(result)) == ["no_image", "price_anomaly", "spam_text"]


def test_seed_vay_dai_trung_ten_cho_duyet_55():
    result = product(name="Váy dài", description="Váy đẹp giá tốt, xem thêm tại https://bit.ly/vay-dep",
                     price=280000, image_count=1, duplicate_names={rules.normalize("Váy dài")})
    assert (result["risk_score"], result["decision"]) == (55, "pending")


# ---- Shop ----

def test_shop_thieu_dia_chi_va_mo_ta_ngan():
    result = detect.score("shop", {"name": "Shop A", "description": "", "address": ""})
    assert sorted(rule_names(result)) == ["missing_address", "short_description"]
    assert result["decision"] == "approved" and result["risk_score"] == 20


def test_shop_day_du_thong_tin_duoc_duyet():
    result = detect.score("shop", {"name": "Shop A", "description": "Cửa hàng thời trang chuyên các mẫu dễ mặc.", "address": "12 Nguyễn Huệ"})
    assert result["risk_score"] == 0


def test_loai_doi_tuong_khong_hop_le():
    with pytest.raises(ValueError):
        detect.score("order", {})