from django.contrib import messages
from django.contrib.auth import logout
from django.shortcuts import redirect
from django.urls import reverse

from .flow import MFA_VERIFIED


class EnforceMFAMiddleware:
    """
    ชั้นป้องกันซ้ำ: session ที่เข้าสู่ระบบแล้วต้องผ่าน MFA เสมอ
    ถ้าพบ session ที่ login แต่ไม่มีเครื่องหมาย MFA (เช่นเข้าทางอื่น) จะถูกออกจากระบบทันที
    และผู้ที่ต้องเปลี่ยนรหัสผ่านจะเข้าได้แค่หน้าเปลี่ยนรหัสผ่านกับออกจากระบบ
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        user = getattr(request, "user", None)
        if user is not None and user.is_authenticated:
            if not request.session.get(MFA_VERIFIED):
                logout(request)
                messages.warning(request, "กรุณาเข้าสู่ระบบใหม่")
                return redirect("accounts:login")
            if user.must_change_password:
                allowed = {
                    reverse("accounts:password_change"),
                    reverse("accounts:logout"),
                    reverse("accounts:backup_codes"),  # ผู้ใช้ใหม่ต้องเห็นรหัสสำรองก่อน
                }
                if request.path not in allowed and not request.path.startswith("/static/"):
                    return redirect("accounts:password_change")
        return self.get_response(request)
