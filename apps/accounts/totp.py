"""
TOTP ตามมาตรฐาน RFC 6238 (ใช้กับ Microsoft Authenticator, Google Authenticator ฯลฯ)

เขียนเองด้วย standard library เพื่อลดการพึ่งพาแพ็กเกจภายนอก และทดสอบกับค่าทดสอบของ RFC
ไฟล์นี้ไม่ import Django จึงทดสอบแยกได้
"""
import base64
import hashlib
import hmac
import secrets
import struct
import time
from urllib.parse import quote, urlencode

DIGITS = 6
PERIOD = 30
# ยอมรับรหัสคลาดเคลื่อน ±1 ช่วงเวลา (±30 วินาที) เผื่อนาฬิกามือถือไม่ตรง
VALID_WINDOW = 1


def generate_secret():
    """สุ่ม secret 160 บิต แล้วเข้ารหัสแบบ base32 ตามที่แอป Authenticator ใช้"""
    return base64.b32encode(secrets.token_bytes(20)).decode("ascii").rstrip("=")


def _decode_secret(secret_b32):
    padded = secret_b32.upper() + "=" * (-len(secret_b32) % 8)
    return base64.b32decode(padded)


def time_step(at=None):
    return int((time.time() if at is None else at) // PERIOD)


def hotp(key_bytes, counter, digits=DIGITS, digest=hashlib.sha1):
    mac = hmac.new(key_bytes, struct.pack(">Q", counter), digest).digest()
    offset = mac[-1] & 0x0F
    code = struct.unpack(">I", mac[offset:offset + 4])[0] & 0x7FFFFFFF
    return str(code % (10 ** digits)).zfill(digits)


def code_at(secret_b32, step):
    return hotp(_decode_secret(secret_b32), step)


def verify(secret_b32, code, last_used_step=None, at=None):
    """
    ตรวจรหัส คืนค่า step ที่ใช้ได้ หรือ None ถ้าไม่ถูกต้อง

    ปฏิเสธรหัสจาก step ที่ใช้ไปแล้ว (หรือเก่ากว่า) เพื่อกันการนำรหัสเดิมมาใช้ซ้ำ
    """
    code = (code or "").strip().replace(" ", "")
    if len(code) != DIGITS or not code.isdigit():
        return None
    now = time_step(at)
    key = _decode_secret(secret_b32)
    for step in range(now - VALID_WINDOW, now + VALID_WINDOW + 1):
        if last_used_step is not None and step <= last_used_step:
            continue
        if hmac.compare_digest(hotp(key, step), code):
            return step
    return None


def provisioning_uri(secret_b32, account_name, issuer):
    """ข้อความที่ใส่ใน QR code ให้แอป Authenticator สแกน"""
    label = quote(f"{issuer}:{account_name}", safe=":")
    params = urlencode(
        {"secret": secret_b32, "issuer": issuer, "digits": DIGITS, "period": PERIOD},
        quote_via=quote,  # ช่องว่างเป็น %20 ไม่ใช่ + เพราะบางแอปแสดง + ตามตัว
    )
    return f"otpauth://totp/{label}?{params}"
