"""Hộp thư hỗ trợ Buyer/Seller với Admin."""
from flask import Blueprint, g, request

from ..services.auth import require_role
from ..services.db import get_db
from ..services.responses import fail, ok

bp = Blueprint("tickets", __name__, url_prefix="/api/tickets")
MAX_TICKETS = 500
MAX_SUBJECT_LENGTH = 120
MAX_CONTENT_LENGTH = 4000


def _profile(db, user_id):
    rows = db.table("profiles").select("id,username,full_name,role").eq(
        "id", user_id).limit(1).execute().data
    return rows[0] if rows else None


def _profiles(db, user_ids):
    if not user_ids:
        return {}
    rows = db.table("profiles").select("id,username,full_name,role").in_(
        "id", list(user_ids)).limit(MAX_TICKETS).execute().data
    return {row["id"]: row for row in rows}


def _ticket_view(db, ticket, profiles, replies):
    profile = profiles.get(ticket["user_id"]) or _profile(db, ticket["user_id"]) or {}
    return {
        "id": ticket["id"],
        "user_id": ticket["user_id"],
        "user_name": profile.get("full_name") or profile.get("username") or "Người dùng",
        "user_role": profile.get("role"),
        "subject": ticket.get("subject") or "Phản hồi hỗ trợ",
        "content": ticket["content"],
        "status": ticket.get("status", "open"),
        "created_at": ticket.get("created_at"),
        "replies": [
            {
                "id": reply["id"],
                "user_id": reply["user_id"],
                "user_name": (profiles.get(reply["user_id"]) or {}).get("full_name")
                or (profiles.get(reply["user_id"]) or {}).get("username")
                or "Người dùng",
                "user_role": (profiles.get(reply["user_id"]) or {}).get("role"),
                "content": reply["content"],
                "created_at": reply.get("created_at"),
            }
            for reply in replies
        ],
    }


@bp.get("")
@require_role("buyer", "seller", "admin")
def list_tickets():
    """Admin xem mọi ticket; Buyer/Seller chỉ xem ticket của mình."""
    db = get_db()
    query = db.table("tickets").select("id,user_id,parent_id,subject,content,status,created_at")
    if g.user["role"] != "admin":
        query = query.eq("user_id", g.user["id"])
    rows = query.order("created_at", desc=True).limit(MAX_TICKETS).execute().data
    roots = [row for row in rows if row.get("parent_id") is None]
    reply_rows = (db.table("tickets").select("id,user_id,parent_id,subject,content,status,created_at").order("created_at")
                  .limit(MAX_TICKETS).execute().data)
    grouped = {}
    for reply in reply_rows:
        if reply.get("parent_id") is not None:
            grouped.setdefault(reply["parent_id"], []).append(reply)

    user_ids = {row["user_id"] for row in rows + reply_rows}
    profiles = _profiles(db, user_ids)
    result = [_ticket_view(db, root, profiles, grouped.get(root["id"], [])) for root in roots]
    return ok({"items": result})


@bp.post("")
@require_role("buyer", "seller")
def create_ticket():
    """Tạo ticket mới cho Admin."""
    body = request.get_json(silent=True) or {}
    subject = str(body.get("subject") or "").strip()
    content = str(body.get("content") or "").strip()
    if not subject or len(subject) > MAX_SUBJECT_LENGTH:
        return fail("INVALID_INPUT", "Chủ đề phải có từ 1 đến 120 ký tự.", 400)
    if not content or len(content) > MAX_CONTENT_LENGTH:
        return fail("INVALID_INPUT", "Nội dung phải có từ 1 đến 4000 ký tự.", 400)

    db = get_db()
    ticket = db.table("tickets").insert({
        "user_id": g.user["id"],
        "parent_id": None,
        "subject": subject,
        "content": content,
    }).execute().data[0]
    return ok(_ticket_view(db, ticket, {g.user["id"]: g.user}, []), 201)


@bp.post("/<int:ticket_id>/reply")
@require_role("buyer", "seller", "admin")
def reply_to_ticket(ticket_id):
    """Admin và người tạo ticket có thể trả lời trong cùng luồng."""
    body = request.get_json(silent=True) or {}
    content = str(body.get("content") or "").strip()
    if not content or len(content) > MAX_CONTENT_LENGTH:
        return fail("INVALID_INPUT", "Nội dung phải có từ 1 đến 4000 ký tự.", 400)

    db = get_db()
    rows = (db.table("tickets").select("id,user_id,parent_id,subject,content,status,created_at")
            .eq("id", ticket_id).limit(1).execute().data)
    if not rows or rows[0].get("parent_id") is not None:
        return fail("NOT_FOUND", "Không tìm thấy yêu cầu hỗ trợ.", 404)
    root = rows[0]
    if g.user["role"] != "admin" and root["user_id"] != g.user["id"]:
        return fail("NOT_FOUND", "Không tìm thấy yêu cầu hỗ trợ.", 404)

    reply = db.table("tickets").insert({
        "user_id": g.user["id"],
        "parent_id": ticket_id,
        "subject": None,
        "content": content,
    }).execute().data[0]
    return ok(reply, 201)
