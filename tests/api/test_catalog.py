"""Test logic danh sách sản phẩm (không cần Supabase)."""
from api.services import catalog


def make_row(pid, name, price, category="ao", shop_id=1, shop="Shop A", sold=0,
             sizes=(("M", 5),), ratings=(), images=(), created="2026-10-01"):
    return {
        "id": pid, "name": name, "description": f"Mô tả của {name} đủ dài để hiển thị",
        "price": price, "category": category, "shop_id": shop_id, "shops": {"name": shop},
        "sold_count": sold, "created_at": created,
        "product_variants": [{"size": s, "stock": st} for s, st in sizes],
        "reviews": [{"rating": r} for r in ratings],
        "product_images": [dict(url=u, is_main=m, position=p) for u, m, p in images],
    }


ROWS = [
    make_row(1, "Áo thun basic", 150000, sold=5, ratings=(5, 4), images=[("b.jpg", False, 1), ("a.jpg", True, 0)]),
    make_row(2, "Quần jeans", 380000, category="quan", shop_id=2, shop="Denim Store", sold=9, sizes=(("L", 0),)),
    make_row(3, "Váy chữ A", 270000, category="vay-dam", sold=1, sizes=(("S", 3), ("M", 0))),
]


def test_normalize_bo_dau():
    assert catalog.normalize("Áo Đẹp") == "ao dep"


def test_build_card_dung_hop_dong():
    card = catalog.build_card(ROWS[0])
    assert card["image_url"] == "a.jpg"            # ưu tiên ảnh is_main
    assert card["rating_avg"] == 4.5 and card["rating_count"] == 2
    assert card["shop_name"] == "Shop A"
    assert set(card) == {"id", "name", "short_description", "price", "category", "image_url",
                         "shop_id", "shop_name", "rating_avg", "rating_count", "sold_count"}


def test_chua_co_danh_gia():
    assert catalog.rating_stats([]) == (0.0, 0)


def test_tim_kiem_khong_dau_va_theo_shop():
    assert [r["id"] for r in catalog.filter_rows(ROWS, q="ao thun")] == [1]
    assert [r["id"] for r in catalog.filter_rows(ROWS, q="denim")] == [2]


def test_loc_size_chi_tinh_con_hang():
    assert [r["id"] for r in catalog.filter_rows(ROWS, size="M")] == [1]      # váy hết size M
    assert [r["id"] for r in catalog.filter_rows(ROWS, size="L")] == []       # quần hết size L


def test_loc_gia_va_danh_muc():
    assert [r["id"] for r in catalog.filter_rows(ROWS, min_price=200000, max_price=300000)] == [3]
    assert [r["id"] for r in catalog.filter_rows(ROWS, category="quan")] == [2]


def test_sap_xep():
    assert [r["id"] for r in catalog.sort_rows(ROWS, "price_asc")] == [1, 3, 2]
    assert [r["id"] for r in catalog.sort_rows(ROWS, "price_desc")] == [2, 3, 1]
    assert [r["id"] for r in catalog.sort_rows(ROWS, "popular")] == [2, 1, 3]


def test_phan_trang():
    page = catalog.paginate(list(range(20)), 3, 9)
    assert page == {"items": [18, 19], "page": 3, "page_size": 9, "total": 20}
    assert catalog.paginate(list(range(5)), 0, 1000)["page_size"] == catalog.MAX_PAGE_SIZE


def test_build_detail_co_bien_the():
    variants = [{"id": 2, "size": "L", "color": "Đen", "stock": 4}, {"id": 1, "size": "M", "color": "Đen", "stock": 0}]
    row = dict(ROWS[0], tags=["basic"], suits_shapes=[], shops={"id": 1, "name": "Shop A", "owner_id": "u1"})
    detail = catalog.build_detail(row, variants)
    assert [v["id"] for v in detail["variants"]] == [1, 2]
    assert detail["shop"] == {"id": 1, "name": "Shop A", "owner_id": "u1"}
    assert detail["images"][0]["is_main"] is True