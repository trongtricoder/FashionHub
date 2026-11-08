"""Kiểm tra file ảnh tải lên bằng nội dung thật (không tin đuôi file hay Content-Type do trình duyệt gửi)."""

MAX_UPLOAD_BYTES = 5 * 1024 * 1024  # 5 MB


def sniff_image(data):
    """Nhận diện JPG, PNG, WEBP theo vài byte đầu. Trả về (đuôi file, content-type) hoặc None."""
    if data[:3] == b"\xff\xd8\xff":
        return "jpg", "image/jpeg"
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return "png", "image/png"
    if data[:4] == b"RIFF" and data[8:12] == b"WEBP":
        return "webp", "image/webp"
    return None