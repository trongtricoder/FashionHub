"""Build VietQR transfer instructions and QR images locally."""
import base64
from io import BytesIO
import os
import re

import qrcode
from qrcode.image.svg import SvgPathImage


def payment_settings():
    """Validate server-side settings required to create a transfer QR."""
    settings = {
        "bank_bin": os.environ.get("PAYMENT_BANK_BIN", "").strip(),
        "bank_name": os.environ.get("PAYMENT_BANK_NAME", "").strip(),
        "account_number": os.environ.get("PAYMENT_ACCOUNT_NUMBER", "").strip(),
        "account_name": os.environ.get("PAYMENT_ACCOUNT_NAME", "").strip(),
    }
    if not re.fullmatch(r"\d{6}", settings["bank_bin"]):
        raise ValueError("Chưa cấu hình mã ngân hàng nhận thanh toán.")
    if not re.fullmatch(r"[A-Za-z0-9]{6,20}", settings["account_number"]):
        raise ValueError("Chưa cấu hình số tài khoản nhận thanh toán.")
    if not settings["account_name"] or len(settings["account_name"].encode("utf-8")) > 25:
        raise ValueError("Tên chủ tài khoản nhận thanh toán không hợp lệ.")
    if not settings["bank_name"]:
        raise ValueError("Chưa cấu hình tên ngân hàng nhận thanh toán.")
    return settings


def _tlv(tag, value):
    encoded_length = len(value.encode("utf-8"))
    if encoded_length > 99:
        raise ValueError("Nội dung QR vượt quá giới hạn.")
    return f"{tag}{encoded_length:02d}{value}"


def _crc16(payload):
    crc = 0xFFFF
    for byte in payload.encode("utf-8"):
        crc ^= byte << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return f"{crc:04X}"


def transfer_payload(settings, order_id, amount):
    """Build EMVCo/VietQR transfer payload with order-specific amount and note."""
    if isinstance(amount, bool) or not isinstance(amount, int) or amount < 0:
        raise ValueError("Số tiền chuyển khoản không hợp lệ.")

    reference = f"FHORDER{order_id}"
    beneficiary = "".join((
        _tlv("00", settings["bank_bin"]),
        _tlv("01", settings["account_number"]),
    ))
    merchant_account = "".join((
        _tlv("00", "A000000727"),
        _tlv("01", beneficiary),
        _tlv("02", "QRIBFTTA"),
    ))
    additional_data = _tlv("08", reference)
    payload = "".join((
        _tlv("00", "01"),
        _tlv("01", "12"),
        _tlv("38", merchant_account),
        _tlv("53", "704"),
        _tlv("54", str(amount)),
        _tlv("58", "VN"),
        _tlv("62", additional_data),
        "6304",
    ))
    return payload + _crc16(payload)


def qr_data_url(payload):
    """Return an SVG QR data URL without sending payment details to an external service."""
    qr = qrcode.QRCode(error_correction=qrcode.constants.ERROR_CORRECT_M, border=4, box_size=6)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image(image_factory=SvgPathImage)
    output = BytesIO()
    image.save(output)
    encoded = base64.b64encode(output.getvalue()).decode("ascii")
    return "data:image/svg+xml;base64," + encoded


def instructions_for_orders(orders, settings):
    """Create one QR per order because checkout may split cart items across shops."""
    instructions = []
    for order in orders:
        payload = transfer_payload(settings, order["id"], order["total"])
        instructions.append({
            "order_id": order["id"],
            "amount": order["total"],
            "reference": f"FHORDER{order['id']}",
            "qr_data_url": qr_data_url(payload),
        })
    return {
        "recipient_name": settings["account_name"],
        "bank_name": settings["bank_name"],
        "instructions": instructions,
    }
