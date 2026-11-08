"""Ghi kết quả kiểm duyệt của AI Detector: hàng đợi Admin, nhật ký chặn, cảnh báo và khóa tài khoản (mục 10.3)."""
from datetime import datetime, timedelta, timezone

from ai.detector import rules


def other_shop_product_names(db, shop_id):
    """Tên đã chuẩn hóa của sản phẩm thuộc shop khác, dùng cho luật trùng tên."""
    rows = db.table("products").select("shop_id,name").execute().data
    return {rules.normalize(r["name"]).strip() for r in rows if r["shop_id"] != shop_id}


def apply_decision(db, target_type, target_id, owner_id, result):
    """Ghi hệ quả của một quyết định kiểm duyệt. Trả về thông tin xử lý tài khoản hoặc None.

    approved: dọn các mục chờ duyệt cũ của đối tượng này.
    pending, blocked: đưa vào hàng đợi cho Admin (blocked cũng vào để Admin xem lại), ghi nhật ký.
    blocked: cảnh báo hoặc khóa tài khoản tùy số lần bị chặn trong 7 ngày gần nhất.
    Việc cập nhật moderation_status của chính sản phẩm hoặc shop do nơi gọi làm.
    """
    # Mỗi lần sửa chỉ giữ một mục chờ duyệt mới nhất cho cùng đối tượng
    db.table("moderation_queue").delete().eq("target_type", target_type).eq("target_id", target_id).eq("status", "pending").execute()
    decision = result["decision"]
    if decision == "approved":
        return None

    db.table("moderation_queue").insert({
        "target_type": target_type, "target_id": target_id,
        "risk_score": result["risk_score"], "reasons": result["reasons"],
    }).execute()
    db.table("ai_block_logs").insert({
        "target_type": target_type, "target_id": str(target_id), "owner_id": owner_id,
        "risk_score": result["risk_score"], "reasons": result["reasons"],
        "action": "blocked" if decision == "blocked" else "pending_review",
    }).execute()
    if decision == "blocked":
        return escalate_account(db, owner_id)
    return None


def escalate_account(db, owner_id):
    """Từ 1 đến 2 mục bị chặn trong 7 ngày: cảnh báo. Từ 3 trở lên: khóa tài khoản."""
    since = (datetime.now(timezone.utc) - timedelta(days=rules.WARNING_WINDOW_DAYS)).isoformat()
    blocked = db.table("ai_block_logs").select("id").eq("owner_id", owner_id).eq("action", "blocked").gte("created_at", since).execute().data
    count = len(blocked)
    action = "ban" if count >= rules.BAN_AFTER_BLOCKED else "warning"
    if action == "ban":
        db.table("profiles").update({"status": "banned"}).eq("id", owner_id).execute()
    db.table("ai_block_logs").insert({
        "target_type": "account", "target_id": str(owner_id), "owner_id": owner_id,
        "reasons": [{"rule": "blocked_count", "points": 0,
                     "detail": f"{count} mục bị chặn trong {rules.WARNING_WINDOW_DAYS} ngày gần nhất"}],
        "action": action,
    }).execute()
    return {"action": action, "blocked_count": count}