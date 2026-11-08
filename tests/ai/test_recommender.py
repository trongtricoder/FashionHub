"""Test gợi ý sản phẩm theo công thức điểm (mục 10.2): bảng size, từng thành phần, tổng điểm, lý do."""
import pytest

from ai.recommender import score, size_chart


def candidate(pid=1, shop=1, name="Áo thun basic", price=250000, tags=("toi-gian", "basic"), shapes=("hourglass", "pear"),
              sold=5, avg=4.5, count=2, sizes=("L", "M")):
    return {"id": pid, "shop_id": shop, "name": name, "price": price, "tags": list(tags), "suits_shapes": list(shapes),
            "sold_count": sold, "rating_avg": avg, "rating_count": count, "sizes": set(sizes)}


PROFILE = {"height_cm": 170, "weight_kg": 60, "body_shape": "hourglass", "style_tags": ["toi-gian", "cong-so"],
           "budget_max": 300000, "wishes": ""}


# ---------- bảng size ----------

@pytest.mark.parametrize("height,weight,size", [
    (158, 50, "S"), (160, 52, "S"), (161, 50, "M"), (160, 53, "M"),    # sát ranh giới
    (170, 60, "L"),    # cao ra L, nặng ra M, lấy bậc lớn hơn
    (165, 80, "XL"), (176, 72, "L"), (177, 55, "XL"), (190, 60, "XXL"), (165, 90, "XXL"),
])
def test_size_goi_y(height, weight, size):
    assert size_chart.recommend_size(height, weight) == size


def test_thieu_so_do_thi_khong_goi_y_size():
    assert size_chart.recommend_size(None, 60) is None and size_chart.recommend_size(170, 0) is None


def test_thu_tu_size():
    assert size_chart.rank("s") == 0 and size_chart.rank("XXL") == 4 and size_chart.rank("Free") is None


# ---------- từng thành phần ----------

def test_size_ok_dung_lech_mot_bac_xa_va_free_size():
    assert score.size_ok("L", {"M", "L"}) == 1.0
    assert score.size_ok("L", {"M", "XL"}) == 0.5          # sai một bậc
    assert score.size_ok("L", {"S", "XXL"}) == 0.0         # xa hơn một bậc
    assert score.size_ok("L", {"Free"}) == 0.5             # hàng không chia size thì trung tính
    assert score.size_ok(None, {"M"}) == 0.5


def test_shape_ok():
    assert score.shape_ok("pear", ["pear", "apple"]) == 1.0
    assert score.shape_ok("rectangle", ["pear"]) == 0.0
    assert score.shape_ok("pear", []) == 0.5               # sản phẩm không ghi dáng phù hợp


def test_fit_style_jaccard():
    assert score.fit_style(["a", "b"], ["a", "c"]) == pytest.approx(1 / 3)
    assert score.fit_style(["a"], ["a"]) == 1.0
    assert score.fit_style([], ["a"]) == 0.5               # người mua chưa chọn phong cách
    assert score.fit_style(["a"], []) == 0.0


def test_fit_budget():
    assert score.fit_budget(250000, 300000) == 1.0 and score.fit_budget(250000, None) == 1.0
    assert score.fit_budget(450000, 300000) == pytest.approx(0.5)
    assert score.fit_budget(700000, 300000) == 0.0         # vượt hơn gấp đôi thì về 0, không âm


def test_rating_va_popularity():
    assert score.rating_norm(4.5, 2) == pytest.approx(0.9) and score.rating_norm(0, 0) == 0.6
    assert score.popularity_norm(5, 10) == 0.5 and score.popularity_norm(20, 10) == 1.0 and score.popularity_norm(0, 0) == 0.0


# ---------- tổng điểm và lý do ----------

def test_tong_diem_dung_cong_thuc():
    result = score.score_candidate(PROFILE, candidate(), max_sold=10)
    # size 1.0, style 1/3, budget 1.0, rating 0.9, popularity 0.5
    expected = 100 * (0.30 * 1.0 + 0.25 * (1 / 3) + 0.20 * 1.0 + 0.15 * 0.9 + 0.10 * 0.5)
    assert result["score"] == round(expected, 1) == 76.8
    assert result["reasons"] == ["Hợp size L theo số đo của bạn", "Nằm trong ngân sách", "Được đánh giá cao"]


def test_ly_do_toi_da_3_va_chi_nhung_thanh_phan_tu_0_7():
    great = candidate(tags=("toi-gian", "cong-so"), sold=10, avg=5, count=3)
    result = score.score_candidate(PROFILE, great, max_sold=10)
    assert len(result["reasons"]) == 3
    assert result["reasons"][0] == "Hợp size L theo số đo của bạn" and result["reasons"][1] == "Hợp phong cách tối giản, công sở"
    poor = candidate(shapes=("rectangle",), sizes=("XXL",), tags=("vintage",), price=1000000, sold=0, avg=0, count=0)
    assert score.score_candidate(PROFILE, poor, max_sold=10)["reasons"] == []


def test_ly_do_hop_dang_khi_size_khong_dung_hoan_toan():
    result = score.score_candidate(dict(PROFILE, style_tags=[]), candidate(sizes=("XL",), sold=0, count=0, avg=0), max_sold=10)
    assert "Hợp dáng người đồng hồ cát" in result["reasons"]


def test_khong_noi_trong_ngan_sach_khi_nguoi_mua_chua_dat_ngan_sach():
    result = score.score_candidate(dict(PROFILE, budget_max=None), candidate(), max_sold=10)
    assert "Nằm trong ngân sách" not in result["reasons"] and result["parts"]["budget"] == 1.0


def test_hang_free_size_khong_co_ly_do_hop_size():
    acc = candidate(name="Túi tote", tags=(), shapes=(), sizes=("Free",), sold=0, avg=0, count=0)
    result = score.score_candidate(PROFILE, acc, max_sold=10)
    assert result["parts"]["size"] == pytest.approx(0.5) and not any("size" in r for r in result["reasons"])


# ---------- mong muốn của người mua ----------

def test_mong_muon_khop_tag_cong_5_diem_va_dung_dau_ly_do():
    base = score.score_candidate(PROFILE, candidate(), 10)["score"]
    wished = score.score_candidate(PROFILE, candidate(), 10, "mình thích phong cách tối giản")
    assert wished["score"] == pytest.approx(base + 5) and wished["reasons"][0] == "Đúng mong muốn của bạn"
    assert len(wished["reasons"]) == 3


def test_mong_muon_khop_ten_san_pham_va_bo_qua_tu_qua_ngan():
    assert score.wish_matches("tìm áo thun đi chơi", candidate(name="Áo thun basic"))
    assert not score.wish_matches("tìm áo đi chơi", candidate(name="Áo thun basic", tags=()))        # "áo" chỉ 2 ký tự
    assert not score.wish_matches("", candidate())
    assert score.wish_matches("muốn một chiếc sơ mi", candidate(name="Áo sơ mi trắng", tags=()))     # tên có từ ngắn, khớp theo cặp
    assert score.wish_matches("muốn đồ mùa đông", candidate(tags=("mua-dong",), name="Hoodie xyz"))


def test_diem_toi_da_100():
    best = candidate(tags=("toi-gian", "cong-so"), sold=10, avg=5, count=9)
    assert score.score_candidate(PROFILE, best, 10, "tối giản")["score"] <= 100


# ---------- chọn kết quả ----------

def test_sap_xep_theo_diem_roi_ban_chay_roi_id():
    high = candidate(pid=1, shop=1, sold=1)
    low = candidate(pid=2, shop=2, shapes=("rectangle",), sizes=("XXL",), tags=("vintage",))
    result = score.recommend(PROFILE, [low, high], limit=5)
    assert [r["id"] for r in result] == [1, 2]
    same_a, same_b = candidate(pid=7, shop=1, sold=5), candidate(pid=3, shop=2, sold=5)
    assert [r["id"] for r in score.recommend(PROFILE, [same_a, same_b], limit=5)] == [3, 7]       # bằng điểm thì id nhỏ trước


def test_moi_shop_toi_da_3_san_pham():
    many = [candidate(pid=i, shop=1) for i in range(1, 7)] + [candidate(pid=10, shop=2, shapes=("rectangle",), sizes=("XXL",))]
    result = score.recommend(PROFILE, many, limit=10)
    assert [r["id"] for r in result if r["id"] < 10] == [1, 2, 3] and 10 in [r["id"] for r in result]
    assert len(result) == 4


def test_gioi_han_so_luong_va_danh_sach_rong():
    assert len(score.recommend(PROFILE, [candidate(pid=i, shop=i) for i in range(1, 6)], limit=2)) == 2
    assert score.recommend(PROFILE, [], limit=5) == []