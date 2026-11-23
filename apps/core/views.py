import platform

import django
from django.conf import settings
from django.contrib.auth.decorators import login_not_required
from django.db import connection
from django.http import Http404, HttpResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache

from apps.accounts import permissions
from apps.accounts.security import client_ip

from . import checks


def _can_view_status(user):
    return settings.DEBUG or permissions.has_capability(user, "view_system_status")


@login_not_required
@never_cache
def healthz(request):
    """ใช้โดย Docker และระบบเฝ้าระวัง ตอบแค่ ok/error ไม่เปิดเผยรายละเอียดระบบ"""
    try:
        with connection.cursor() as cur:
            cur.execute("SELECT 1")
    except Exception:  # noqa: BLE001
        return HttpResponse("error", status=503, content_type="text/plain")
    return HttpResponse("ok", content_type="text/plain")


def home(request):
    """หน้าหลักหลังเข้าสู่ระบบ: งานที่รอท่าน และทางลัดตามบทบาท"""
    from apps.workflow import services as wf_services

    tasks = (
        wf_services.actionable_tasks(request.user)
        .select_related("instance__document__registration", "assignee")
        .order_by("due_at", "created_at")
    )
    return render(
        request,
        "core/home.html",
        {
            "assignments": permissions.active_roles(request.user),
            "task_count": tasks.count(),
            "tasks": tasks[:5],
        },
    )


def status(request):
    """หน้าสถานะระบบ แสดงข้อมูลเวอร์ชัน จึงจำกัดเฉพาะโหมดพัฒนาหรือผู้ดูแลระบบ"""
    if not _can_view_status(request.user):
        raise Http404
    results = checks.run_all()
    context = {
        "results": results,
        "all_ok": all(r.ok for r in results),
        "django_version": django.get_version(),
        "python_version": platform.python_version(),
        "settings_module": settings.SETTINGS_MODULE,
        "debug": settings.DEBUG,
        "installed_modules": [app for app in settings.INSTALLED_APPS if app.startswith("apps.")],
        # ใช้ตรวจว่าตั้งค่า proxy ถูก: IP นี้ต้องตรงกับ IP จริงของเครื่องที่เปิดหน้านี้
        "seen_ip": client_ip(request),
        "storage_backend": settings.ESARABAN_STORAGE_BACKEND,
    }
    return render(request, "core/status.html", context)
