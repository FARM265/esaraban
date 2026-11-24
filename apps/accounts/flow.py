"""
สถานะระหว่างการเข้าสู่ระบบ 2 ขั้น เก็บใน session

ขั้นที่ 1 ผ่านรหัสผ่านแล้ว -> เก็บ PENDING_USER (ยังไม่ถือว่าเข้าสู่ระบบ)
ขั้นที่ 2 ผ่าน MFA แล้ว   -> เรียก django login() และตั้ง MFA_VERIFIED
ถ้าปิด MFA (ESARABAN_LOGIN_REQUIRE_MFA=False) ข้ามขั้นที่ 2 ไปเลย MFA_VERIFIED จึงหมายถึง
"เข้าสู่ระบบผ่านหน้าเข้าสู่ระบบของระบบครบแล้ว" ซึ่ง EnforceMFAMiddleware ใช้ตรวจ
"""
import time

from django.contrib.auth import get_user_model, login
from django.utils.http import url_has_allowed_host_and_scheme

PENDING_USER = "es_pending_user"
PENDING_AT = "es_pending_at"
PENDING_NEXT = "es_pending_next"
SETUP_SECRET = "es_mfa_setup_secret"
SHOW_BACKUP_CODES = "es_show_backup_codes"
MFA_VERIFIED = "es_mfa_verified"

PENDING_TTL_SECONDS = 300  # ต้องยืนยัน MFA ภายใน 5 นาทีหลังใส่รหัสผ่าน


def safe_next(request, url):
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return ""


def start_pending(request, user, next_url=""):
    request.session.cycle_key()  # ป้องกัน session fixation
    request.session[PENDING_USER] = str(user.pk)
    request.session[PENDING_AT] = int(time.time())
    request.session[PENDING_NEXT] = safe_next(request, next_url)
    request.session.pop(SETUP_SECRET, None)


def pending_user(request):
    """ผู้ใช้ที่ผ่านรหัสผ่านแล้วแต่ยังไม่ผ่าน MFA หรือ None ถ้าไม่มี/หมดเวลา"""
    user_id = request.session.get(PENDING_USER)
    started = request.session.get(PENDING_AT, 0)
    if not user_id or time.time() - started > PENDING_TTL_SECONDS:
        clear_pending(request)
        return None
    try:
        user = get_user_model().objects.get(pk=user_id, is_active=True)
    except (get_user_model().DoesNotExist, ValueError):
        clear_pending(request)
        return None
    return user


def clear_pending(request):
    for key in (PENDING_USER, PENDING_AT, PENDING_NEXT, SETUP_SECRET):
        request.session.pop(key, None)


def complete_login(request, user):
    """เข้าสู่ระบบจริง หลังผ่านทั้งรหัสผ่านและ MFA คืนค่า URL ที่จะไปต่อ"""
    next_url = request.session.get(PENDING_NEXT, "")
    clear_pending(request)
    user.backend = "django.contrib.auth.backends.ModelBackend"
    login(request, user)
    request.session[MFA_VERIFIED] = True
    return next_url
