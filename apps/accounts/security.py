"""
งานด้านความปลอดภัยของการเข้าสู่ระบบ: เข้ารหัส secret, รหัสสำรอง, ล็อกบัญชี, IP ผู้ใช้
"""
import base64
import hashlib
import hmac
import secrets
from datetime import timedelta

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.contrib.auth import get_user_model
from django.db import transaction
from django.utils import timezone

from . import totp
from .models import BackupCode, LoginAttempt

# ---------------------------------------------------------------------------
# เข้ารหัส TOTP secret ก่อนบันทึกลงฐานข้อมูล
# ---------------------------------------------------------------------------


def _fernet():
    raw = settings.MFA_ENCRYPTION_KEY or settings.SECRET_KEY
    key = base64.urlsafe_b64encode(hashlib.sha256(("mfa:" + raw).encode()).digest())
    return Fernet(key)


def encrypt_secret(secret_b32):
    return _fernet().encrypt(secret_b32.encode()).decode()


def decrypt_secret(token):
    try:
        return _fernet().decrypt(token.encode()).decode()
    except InvalidToken:
        return None


# ---------------------------------------------------------------------------
# MFA
# ---------------------------------------------------------------------------


def verify_user_totp(user, code):
    """ตรวจรหัส 6 หลักของผู้ใช้ ถ้าถูกต้องจะบันทึก step เพื่อกันใช้ซ้ำ"""
    secret = decrypt_secret(user.mfa_secret_encrypted) if user.mfa_secret_encrypted else None
    if not secret:
        return False
    with transaction.atomic():
        # ใช้ get_user_model() ไม่ใช่ type(user) เพราะ request.user เป็น SimpleLazyObject
        locked = get_user_model().objects.select_for_update().get(pk=user.pk)
        step = totp.verify(secret, code, last_used_step=locked.mfa_last_used_step)
        if step is None:
            return False
        locked.mfa_last_used_step = step
        locked.save(update_fields=["mfa_last_used_step"])
    user.mfa_last_used_step = step
    return True


BACKUP_CODE_COUNT = 10
_BACKUP_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"  # ตัดตัวที่สับสนง่าย เช่น O/0 I/1


def _hash_backup_code(code):
    normalized = code.strip().upper().replace("-", "").replace(" ", "")
    return hmac.new(settings.SECRET_KEY.encode(), normalized.encode(), hashlib.sha256).hexdigest()


def generate_backup_codes(user):
    """สร้างรหัสสำรองชุดใหม่ (ลบชุดเดิม) คืนค่ารหัสแบบอ่านได้ ซึ่งแสดงให้ผู้ใช้เห็นได้ครั้งเดียว"""
    codes = []
    for _ in range(BACKUP_CODE_COUNT):
        raw = "".join(secrets.choice(_BACKUP_ALPHABET) for _ in range(10))
        codes.append(f"{raw[:5]}-{raw[5:]}")
    with transaction.atomic():
        user.backup_codes.all().delete()
        BackupCode.objects.bulk_create(
            [BackupCode(user=user, code_hash=_hash_backup_code(c)) for c in codes]
        )
    return codes


def use_backup_code(user, code):
    """ใช้รหัสสำรอง คืนค่า True ถ้าถูกต้องและยังไม่เคยใช้"""
    updated = BackupCode.objects.filter(
        user=user, code_hash=_hash_backup_code(code), used_at__isnull=True
    ).update(used_at=timezone.now())
    return updated == 1


def remaining_backup_codes(user):
    return user.backup_codes.filter(used_at__isnull=True).count()


# ---------------------------------------------------------------------------
# ล็อกบัญชีชั่วคราวเมื่อใส่ผิดหลายครั้ง
# ---------------------------------------------------------------------------


def _window_start():
    return timezone.now() - timedelta(minutes=settings.LOGIN_LOCKOUT_MINUTES)


def is_locked_out(username, ip_address):
    """
    นับเฉพาะครั้งที่ผิดหลังจากเข้าสู่ระบบสำเร็จครั้งล่าสุด ภายในช่วงเวลาที่กำหนด
    ล็อกตามชื่อผู้ใช้ (ไม่ว่าชื่อนั้นจะมีอยู่จริงหรือไม่ จึงเดาชื่อผู้ใช้จากข้อความไม่ได้)
    และล็อกตาม IP เมื่อมีการลองหลายชื่อจากเครื่องเดียว
    """
    since = _window_start()
    username = username.strip().lower()
    last_success = (
        LoginAttempt.objects.filter(username=username, success=True, created_at__gte=since)
        .values_list("created_at", flat=True)
        .first()
    )
    user_failures = LoginAttempt.objects.filter(
        username=username, success=False, created_at__gte=last_success or since
    ).count()
    if user_failures >= settings.LOGIN_MAX_FAILURES:
        return True
    if ip_address:
        ip_failures = LoginAttempt.objects.filter(
            ip_address=ip_address, success=False, created_at__gte=since
        ).count()
        if ip_failures >= settings.LOGIN_MAX_FAILURES_PER_IP:
            return True
    return False


def record_attempt(username, ip_address, success, stage=LoginAttempt.Stage.PASSWORD):
    from apps.audit import services as audit

    username = username.strip().lower()[:150]
    LoginAttempt.objects.create(username=username, ip_address=ip_address or None, success=success, stage=stage)
    if success:
        action, summary = "LOGIN", "เข้าสู่ระบบสำเร็จ"
    elif stage == LoginAttempt.Stage.MFA:
        action, summary = "LOGIN_MFA_FAILED", "รหัสยืนยัน MFA ไม่ถูกต้อง"
    else:
        action, summary = "LOGIN_FAILED", "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
    actor = get_user_model().objects.filter(username__iexact=username).first() if success else None
    audit.record("AUTH", action, f"{summary}: {username}", actor=actor, actor_label=username, ip=ip_address)


def client_ip(request):
    """
    IP ของผู้ใช้ เมื่ออยู่หลัง proxy ให้เชื่อเฉพาะ header ที่ proxy ตั้ง (TRUST_PROXY_IP_HEADER=True)
    - nginx ของระบบ: X-Real-IP (ค่าเริ่มต้น)
    - คลาวด์ (Render): ไม่ใช้ header เฉพาะ แต่นับ X-Forwarded-For จากท้ายตาม PROXY_XFF_HOPS
    ถ้าไม่ได้อยู่หลัง proxy ห้ามเปิดค่านี้ เพราะผู้ใช้จะปลอม header ได้
    """
    if settings.TRUST_PROXY_IP_HEADER:
        header = settings.PROXY_CLIENT_IP_HEADER
        meta_key = "HTTP_" + header.upper().replace("-", "_") if header and header.lower() != "none" else ""
        real_ip = request.META.get(meta_key, "").split(",")[0].strip() if meta_key else ""
        if real_ip and _looks_like_ip(real_ip):
            return real_ip
        hops = settings.PROXY_XFF_HOPS
        chain = [part.strip() for part in request.META.get("HTTP_X_FORWARDED_FOR", "").split(",") if part.strip()]
        if hops and len(chain) >= hops and _looks_like_ip(chain[-hops]):
            return chain[-hops]
    return request.META.get("REMOTE_ADDR") or None


def _looks_like_ip(value):
    import ipaddress

    try:
        ipaddress.ip_address(value)
        return True
    except ValueError:
        return False
