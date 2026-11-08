"""API AI (mục 9.6): gợi ý và hỏi đáp cho Seller, gợi ý sản phẩm và chatbot cho Buyer."""
from flask import Blueprint, g, request

from ai.chatbot import bot
from ai.recommender import score
from ai.seller import chat, insights

from ..services import catalog, recommend_data, seller_data
from ..services.auth import require_role
from ..services.db import get_db
from ..services.queries import fetch_product_rows, shop_of_owner
from ..services.responses import fail, ok

bp = Blueprint("ai", __name__, url_prefix="/api/ai")

MAX_MESSAGE = 300


def _context():
    """Số liệu của shop đang đăng nhập. Trả về (ctx, None) hoặc (None, response lỗi)."""
    db = get_db()
    shop = shop_of_owner(db, g.user["id"])
    if not shop:
        return None, fail("SHOP_NOT_FOUND", "Tài khoản của bạn chưa có shop.", 404)
    return seller_data.insight_context(db, shop, seller_data.today_vn()), None


@bp.post("/seller/insights")
@require_role("seller")
def seller_insights():
    """POST /api/ai/seller/insights: thống kê 30 ngày và các gợi ý theo luật."""
    ctx, error = _context()
    if error:
        return error
    return ok(insights.generate(ctx))


@bp.post("/seller/chat")
@require_role("seller")
def seller_chat():
    """POST /api/ai/seller/chat { message }: hỏi đáp bằng số liệu thật của shop."""
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return fail("INVALID_INPUT", "Vui lòng nhập câu hỏi.", 400)
    if len(message) > MAX_MESSAGE:
        return fail("INVALID_INPUT", f"Câu hỏi tối đa {MAX_MESSAGE} ký tự.", 400)
    ctx, error = _context()
    if error:
        return error
    return ok({"reply": chat.answer(message, ctx)})


# ---------- Buyer ----------

DEFAULT_LIMIT, MAX_LIMIT = 8, 20


def _cards(db, ids):
    """Thẻ sản phẩm theo đúng thứ tự của danh sách id."""
    rows = fetch_product_rows(db, ids)
    return {pid: catalog.build_card(rows[pid]) for pid in ids if pid in rows}


@bp.post("/recommend")
@require_role("buyer")
def recommend():
    """POST /api/ai/recommend { limit?, extra_wishes? }: gợi ý theo số đo đã lưu bằng công thức điểm (mục 10.2)."""
    body = request.get_json(silent=True) or {}
    limit = min(max(catalog.parse_int(body.get("limit"), DEFAULT_LIMIT), 1), MAX_LIMIT)
    extra = str(body.get("extra_wishes") or "")[:300]

    db = get_db()
    rows = db.table("body_profiles").select("*").eq("user_id", g.user["id"]).limit(1).execute().data
    if not rows:
        return fail("NO_BODY_PROFILE", "Vui lòng nhập số đo của bạn trước để nhận gợi ý.", 422)

    ranked = score.recommend(rows[0], recommend_data.load_candidates(db), limit, extra)
    cards = _cards(db, [r["id"] for r in ranked])
    items = [{"product": cards[r["id"]], "score": r["score"], "reasons": r["reasons"]} for r in ranked if r["id"] in cards]
    return ok({"items": items})


@bp.post("/chatbot")
def chatbot():
    """POST /api/ai/chatbot { message }: công khai, trả lời câu hỏi thường gặp và gợi ý sản phẩm (mục 10.6)."""
    body = request.get_json(silent=True) or {}
    message = str(body.get("message") or "").strip()
    if not message:
        return fail("INVALID_INPUT", "Vui lòng nhập câu hỏi.", 400)
    if len(message) > MAX_MESSAGE:
        return fail("INVALID_INPUT", f"Câu hỏi tối đa {MAX_MESSAGE} ký tự.", 400)

    db = get_db()
    result = bot.answer(message, recommend_data.chatbot_products(db))
    cards = _cards(db, result["product_ids"])
    return ok({"reply": result["reply"], "products": [cards[pid] for pid in result["product_ids"] if pid in cards]})