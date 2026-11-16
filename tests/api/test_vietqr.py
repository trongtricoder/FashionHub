"""VietQR payload generation stays local and contains the exact order reference."""
import base64
import re
import xml.etree.ElementTree as ET

from api.services import vietqr


SETTINGS = {
    "bank_bin": "970422",
    "bank_name": "MB Bank",
    "account_number": "1234567890",
    "account_name": "HUYNH TRONG TRI",
}


def test_vietqr_payload_contains_transfer_amount_and_reference():
    payload = vietqr.transfer_payload(SETTINGS, 42, 315000)
    assert "FHORDER42" in payload
    assert "315000" in payload
    assert "970422" in payload and "1234567890" in payload
    beneficiary = vietqr._tlv("00", "970422") + vietqr._tlv("01", "1234567890")
    merchant_account = (
        vietqr._tlv("00", "A000000727")
        + vietqr._tlv("01", beneficiary)
        + vietqr._tlv("02", "QRIBFTTA")
    )
    assert vietqr._tlv("38", merchant_account) in payload
    assert re.search(r"6304[0-9A-F]{4}$", payload)
    assert payload[-4:] == vietqr._crc16(payload[:-4])

def test_qr_is_generated_locally_as_svg_data_url():
    payload = vietqr.transfer_payload(SETTINGS, 7, 99000)
    data_url = vietqr.qr_data_url(payload)
    assert data_url.startswith("data:image/svg+xml;base64,")
    svg = base64.b64decode(data_url.split(",", 1)[1])
    assert ET.fromstring(svg).tag.endswith("svg")


def test_instructions_have_individual_qr_for_each_shop_order():
    result = vietqr.instructions_for_orders(
        [{"id": 1, "total": 1000}, {"id": 2, "total": 2000}], SETTINGS)
    assert result["recipient_name"] == "HUYNH TRONG TRI"
    assert result["bank_name"] == "MB Bank"
    assert [item["reference"] for item in result["instructions"]] == ["FHORDER1", "FHORDER2"]
