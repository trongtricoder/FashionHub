"""Sinh mật khẩu tạm cho chức năng Admin đặt lại mật khẩu."""
import secrets
import string

TEMP_PASSWORD_LENGTH = 10
ALPHABET = string.ascii_letters + string.digits


def generate_temp_password(length=TEMP_PASSWORD_LENGTH):
    """Mật khẩu ngẫu nhiên gồm chữ và số, luôn có ít nhất một chữ cái và một chữ số."""
    while True:
        password = "".join(secrets.choice(ALPHABET) for _ in range(length))
        if any(c.isalpha() for c in password) and any(c.isdigit() for c in password):
            return password