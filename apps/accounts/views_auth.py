"""เข้าสู่ระบบ 2 ขั้น ตั้งค่า MFA ออกจากระบบ และเปลี่ยนรหัสผ่าน"""
import segno
from django.conf import settings
from django.contrib import messages
from django.contrib.auth import authenticate, logout, update_session_auth_hash
from django.contrib.auth.decorators import login_not_required
from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.http import urlencode
from django.views.decorators.cache import never_cache
from django.views.decorators.csrf import csrf_protect
from django.views.decorators.debug import sensitive_post_parameters
from django.views.decorators.http import require_POST

from . import flow, security, totp
from .forms import LoginForm, OTPForm, PasswordChangeForm
from .models import LoginAttempt

GENERIC_LOGIN_ERROR = "ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง"
LOCKED_MESSAGE = (
    "มีการเข้าสู่ระบบไม่สำเร็จหลายครั้ง ระบบระงับการเข้าสู่ระบบชั่วคราว "
    "กรุณารอ {minutes} นาทีแล้วลองใหม่ หรือติดต่อผู้ดูแลระบบ"
)


def _locked_message():
    return LOCKED_MESSAGE.format(minutes=settings.LOGIN_LOCKOUT_MINUTES)


@login_not_required
@sensitive_post_parameters("password")
@csrf_protect
@never_cache
def login_view(request):
    if request.user.is_authenticated:
        return redirect(settings.LOGIN_REDIRECT_URL)

    form = LoginForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        username = form.cleaned_data["username"]
        ip = security.client_ip(request)
        if security.is_locked_out(username, ip):
            error = _locked_message()
        else:
            user = authenticate(request, username=username, password=form.cleaned_data["password"])
            if user is None:
                security.record_attempt(username, ip, success=False)
                error = _locked_message() if security.is_locked_out(username, ip) else GENERIC_LOGIN_ERROR
            else:
                flow.start_pending(request, user, request.POST.get("next") or request.GET.get("next", ""))
                return redirect("accounts:mfa_verify" if user.mfa_enabled else "accounts:mfa_setup")

    return render(
        request,
        "accounts/login.html",
        {"form": form, "error": error, "next": request.GET.get("next", "")},
    )


def _verify_attempt_failed(request, user):
    ip = security.client_ip(request)
    security.record_attempt(user.username, ip, success=False, stage=LoginAttempt.Stage.MFA)
    if security.is_locked_out(user.username, ip):
        flow.clear_pending(request)
        messages.error(request, _locked_message())
        return redirect("accounts:login")
    return None


def _finish(request, user):
    security.record_attempt(
        user.username, security.client_ip(request), success=True, stage=LoginAttempt.Stage.MFA
    )
    next_url = flow.complete_login(request, user)
    if user.must_change_password:
        return redirect("accounts:password_change")
    return redirect(next_url or settings.LOGIN_REDIRECT_URL)


@login_not_required
@csrf_protect
@never_cache
def mfa_verify(request):
    user = flow.pending_user(request)
    if user is None:
        messages.info(request, "กรุณาเข้าสู่ระบบอีกครั้ง")
        return redirect("accounts:login")
    if not user.mfa_enabled:
        return redirect("accounts:mfa_setup")

    form = OTPForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        code = form.cleaned_data["code"].strip()
        compact = code.replace(" ", "")
        is_totp = len(compact) == totp.DIGITS and compact.isdigit()  # อย่างอื่นถือเป็นรหัสสำรอง
        ok = security.verify_user_totp(user, code) if is_totp else security.use_backup_code(user, code)
        if ok:
            if not is_totp:
                left = security.remaining_backup_codes(user)
                messages.warning(request, f"ใช้รหัสสำรองแล้ว เหลืออีก {left} รหัส")
            return _finish(request, user)
        locked = _verify_attempt_failed(request, user)
        if locked:
            return locked
        error = "รหัสยืนยันไม่ถูกต้องหรือหมดอายุแล้ว"

    return render(request, "accounts/mfa_verify.html", {"form": form, "error": error, "pending": user})


@login_not_required
@csrf_protect
@never_cache
def mfa_setup(request):
    """ตั้งค่า MFA ครั้งแรก (บังคับทุกคน) secret ยังไม่บันทึกจนกว่าจะยืนยันรหัสได้ถูกต้อง"""
    user = flow.pending_user(request)
    if user is None:
        messages.info(request, "กรุณาเข้าสู่ระบบอีกครั้ง")
        return redirect("accounts:login")
    if user.mfa_enabled:
        return redirect("accounts:mfa_verify")

    secret = request.session.get(flow.SETUP_SECRET)
    if not secret:
        secret = totp.generate_secret()
        request.session[flow.SETUP_SECRET] = secret

    form = OTPForm(request.POST or None)
    error = None
    if request.method == "POST" and form.is_valid():
        step = totp.verify(secret, form.cleaned_data["code"])
        if step is not None:
            user.mfa_secret_encrypted = security.encrypt_secret(secret)
            user.mfa_confirmed_at = timezone.now()
            user.mfa_last_used_step = step
            user.save(update_fields=["mfa_secret_encrypted", "mfa_confirmed_at", "mfa_last_used_step"])
            codes = security.generate_backup_codes(user)
            from apps.audit import services as audit

            audit.record("AUTH", "MFA_ENABLED", f"ตั้งค่า MFA: {user.username}", actor=user,
                         ip=security.client_ip(request))
            _finish(request, user)
            request.session[flow.SHOW_BACKUP_CODES] = codes
            # แสดงรหัสสำรองก่อนเสมอ หน้านั้นจะพาไปต่อ (รวมถึงหน้าเปลี่ยนรหัสผ่านถ้าจำเป็น)
            return redirect("accounts:backup_codes")
        locked = _verify_attempt_failed(request, user)
        if locked:
            return locked
        error = "รหัสยืนยันไม่ถูกต้อง ตรวจว่าเวลาบนมือถือตรงกับเวลาจริง แล้วลองใหม่"

    uri = totp.provisioning_uri(secret, user.username, settings.MFA_ISSUER)
    qr_data_uri = segno.make_qr(uri, error="m").svg_data_uri(scale=5, border=2)
    grouped = " ".join(secret[i:i + 4] for i in range(0, len(secret), 4))
    return render(
        request,
        "accounts/mfa_setup.html",
        {"form": form, "error": error, "qr_data_uri": qr_data_uri, "secret_grouped": grouped, "pending": user},
    )


@never_cache
def backup_codes(request):
    """แสดงรหัสสำรองที่เพิ่งสร้าง ครั้งเดียวเท่านั้น"""
    codes = request.session.pop(flow.SHOW_BACKUP_CODES, None)
    if not codes:
        return redirect("accounts:profile")
    return render(request, "accounts/backup_codes.html", {"codes": codes})


@require_POST
def regenerate_backup_codes(request):
    form = OTPForm(request.POST)
    if form.is_valid() and security.verify_user_totp(request.user, form.cleaned_data["code"]):
        request.session[flow.SHOW_BACKUP_CODES] = security.generate_backup_codes(request.user)
        from apps.audit import services as audit

        audit.record("AUTH", "BACKUP_CODES_REGENERATED", f"สร้างรหัสสำรองใหม่: {request.user.username}",
                     actor=request.user, ip=security.client_ip(request))
        return redirect("accounts:backup_codes")
    messages.error(request, "รหัสยืนยันไม่ถูกต้อง จึงยังไม่สร้างรหัสสำรองใหม่")
    return redirect("accounts:profile")


@login_not_required
@require_POST
def logout_view(request):
    if request.user.is_authenticated:
        from apps.audit import services as audit

        audit.record("AUTH", "LOGOUT", f"ออกจากระบบ: {request.user.username}", actor=request.user,
                     ip=security.client_ip(request))
    logout(request)
    messages.success(request, "ออกจากระบบแล้ว")
    return redirect("accounts:login")


@sensitive_post_parameters()
@never_cache
def password_change(request):
    form = PasswordChangeForm(request.user, request.POST or None)
    if request.method == "POST" and form.is_valid():
        user = form.save()
        user.must_change_password = False
        user.save(update_fields=["must_change_password"])
        update_session_auth_hash(request, user)  # ไม่ต้องเข้าสู่ระบบใหม่ และยังคงสถานะ MFA
        from apps.audit import services as audit

        audit.record("AUTH", "PASSWORD_CHANGED", f"เปลี่ยนรหัสผ่าน: {user.username}", actor=user,
                     ip=security.client_ip(request))
        messages.success(request, "เปลี่ยนรหัสผ่านเรียบร้อยแล้ว")
        return redirect(settings.LOGIN_REDIRECT_URL)
    return render(
        request,
        "accounts/password_change.html",
        {"form": form, "forced": request.user.must_change_password},
    )


@login_not_required
def admin_login_redirect(request):
    """ปิดหน้า login ของ Django admin ไม่ให้ข้าม MFA ได้"""
    nxt = flow.safe_next(request, request.GET.get("next", ""))
    url = reverse("accounts:login")
    if nxt:
        url += "?" + urlencode({"next": nxt})
    return redirect(url)
