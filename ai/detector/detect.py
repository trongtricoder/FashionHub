"""Điểm vào của AI Detector: score(target_type, data) -> { risk_score, decision, reasons }."""
from . import rules


def score(target_type, data):
    """Chấm điểm rủi ro cho một sản phẩm hoặc shop.

    target_type: "product" hoặc "shop".
    data: name, description, và tùy loại:
      - product: price, image_count, duplicate_names (tập tên đã chuẩn hóa của sản phẩm shop khác)
      - shop: address
    Hàm thuần, không đụng database, nên test và giải thích được từng luật.
    """
    if target_type not in ("product", "shop"):
        raise ValueError("target_type phải là 'product' hoặc 'shop'")

    name = data.get("name") or ""
    description = data.get("description") or ""
    found = [
        rules.rule_banned_keyword(name, description),
        rules.rule_external_contact(name, description),
        rules.rule_short_description(description),
        rules.rule_spam_text(name, description),
    ]
    if target_type == "product":
        found += [
            rules.rule_price_anomaly(data.get("price")),
            rules.rule_no_image(data.get("image_count")),
            rules.rule_duplicate(name, data.get("duplicate_names")),
        ]
    else:
        found.append(rules.rule_missing_address(data.get("address")))

    reasons = [r for r in found if r]
    total = min(rules.MAX_SCORE, sum(r["points"] for r in reasons))
    return {"risk_score": total, "decision": rules.decide(total), "reasons": reasons}