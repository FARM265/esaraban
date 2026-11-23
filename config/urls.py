from django.contrib import admin
from django.urls import include, path

from apps.accounts.views_auth import admin_login_redirect

admin.site.site_header = "E-Saraban ผู้ดูแลระบบ"
admin.site.site_title = "E-Saraban"
admin.site.index_title = "จัดการข้อมูลระบบ"

urlpatterns = [
    # หน้า login ของ Django admin ถูกปิด ให้ใช้หน้าเข้าสู่ระบบที่มี MFA แทน (ต้องอยู่ก่อน admin.site.urls)
    path("admin/login/", admin_login_redirect),
    path("admin/", admin.site.urls),
    path("accounts/", include("apps.accounts.urls")),
    path("registry/", include("apps.registry.urls")),
    path("documents/", include("apps.documents.urls")),
    path("workflow/", include("apps.workflow.urls")),
    path("annotations/", include("apps.annotations.urls")),
    path("signatures/", include("apps.signatures.urls")),
    path("letters/", include("apps.letters.urls")),
    path("audit/", include("apps.audit.urls")),
    path("archive/", include("apps.archive.urls")),
    path("reports/", include("apps.reports.urls")),
    path("notifications/", include("apps.notifications.urls")),
    path("", include("apps.core.urls")),
]
