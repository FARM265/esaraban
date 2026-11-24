"""
เมนู Sidebar ของระบบ

แต่ละรายการระบุ url_name ไว้ล่วงหน้า แต่จะแสดงก็ต่อเมื่อ
1) มี URL นั้นอยู่จริงในระบบแล้ว (reverse ได้) และ
2) ผู้ใช้ผ่านเงื่อนไขสิทธิ์ของรายการนั้น
จึงไม่มีทางเกิดเมนูที่กดแล้วไม่มีหน้ารองรับ เมื่อโมดูลใหม่เพิ่ม URL เมนูจะปรากฏเอง
"""
from dataclasses import dataclass
from typing import Callable

from django.conf import settings
from django.urls import NoReverseMatch, reverse

from apps.accounts.permissions import has_capability


def _anyone(user):
    return user.is_authenticated


def _cap(capability):
    def check(user):
        return user.is_authenticated and has_capability(user, capability)

    return check


def _status_viewer(user):
    return user.is_authenticated and (settings.DEBUG or has_capability(user, "view_system_status"))


def _report_exporter(user):
    return user.is_authenticated and (has_capability(user, "view_reports") or has_capability(user, "register_documents"))


def _pending_tasks(user):
    """จำนวนงานที่รอผู้ใช้ (รวมงานที่ปฏิบัติแทน) แสดงท้ายเมนูงานรอดำเนินการ"""
    from apps.workflow.services import actionable_tasks

    return actionable_tasks(user).count()


def _unread_notifications(user):
    from apps.notifications.services import unread_count

    return unread_count(user)


def _calendar_user(user):
    from apps.documents.calendar_views import can_use_calendar

    return user.is_authenticated and can_use_calendar(user)


def _django_admin(user):
    return user.is_authenticated and user.is_superuser


@dataclass(frozen=True)
class MenuItem:
    label: str
    url_name: str
    icon: str
    allowed: Callable = _anyone
    badge: Callable | None = None  # คืนจำนวนที่จะแสดงท้ายเมนู (0 = ไม่แสดง)


MENU = [
    ("งานประจำวัน", [
        MenuItem("หน้าหลัก", "core:home", "grid"),
        MenuItem("ภาพรวม", "reports:dashboard", "grid", _cap("view_reports")),
        MenuItem("งานรอดำเนินการ", "workflow:my_tasks", "inbox", badge=_pending_tasks),
        MenuItem("การแจ้งเตือน", "notifications:index", "bell", badge=_unread_notifications),
        MenuItem("ลงทะเบียนรับ", "documents:receive", "download", _cap("register_documents")),
        MenuItem("สร้างหนังสือ", "letters:create", "edit", _cap("create_documents")),
        MenuItem("เอกสารของฉัน", "documents:list", "file"),
        MenuItem("ลงปฏิทินจากไฟล์", "documents:calendar_upload", "calendar", _calendar_user),
    ]),
    ("ทะเบียนและค้นหา", [
        MenuItem("ทะเบียนเลขหนังสือ", "registry:index", "list", _cap("view_registry")),
        MenuItem("ค้นหาและติดตาม", "reports:search", "search"),
        MenuItem("รายงาน", "reports:reports", "download", _report_exporter),
        MenuItem("คลังเอกสาร", "archive:index", "archive"),
    ]),
    ("ผู้ดูแลระบบ", [
        MenuItem("ผู้ใช้และสิทธิ์", "accounts:user_list", "users", _cap("manage_users")),
        MenuItem("กลุ่มงาน", "accounts:department_list", "building", _cap("manage_users")),
        MenuItem("เส้นทางการเสนอ", "workflow:template_list", "route", _cap("manage_workflows")),
        MenuItem("หัวหนังสือ", "letters:letterhead", "file", _cap("manage_registers")),
        MenuItem("Audit Log", "audit:index", "shield", _cap("view_audit")),
        MenuItem("สถานะระบบ", "core:status", "activity", _status_viewer),
        MenuItem("จัดการข้อมูล (Admin)", "admin:index", "settings", _django_admin),
    ]),
    ("บัญชีของฉัน", [
        MenuItem("ข้อมูลและความปลอดภัย", "accounts:profile", "user"),
        MenuItem("แจ้งเตือนทาง LINE/อีเมล", "notifications:settings", "bell"),
        MenuItem("มอบหมายปฏิบัติราชการแทน", "workflow:delegations", "swap"),
        MenuItem("ลายมือชื่อของฉัน", "signatures:my_signature", "edit", _cap("sign_documents")),
    ]),
]


def build_menu(user, current_path=""):
    groups = []
    for group_label, items in MENU:
        visible = []
        for item in items:
            try:
                url = reverse(item.url_name)
            except NoReverseMatch:
                continue  # โมดูลยังไม่ได้พัฒนา จึงไม่แสดง
            if not item.allowed(user):
                continue
            badge = item.badge(user) if item.badge else 0
            visible.append({"label": item.label, "url": url, "icon": item.icon, "active": False, "badge": badge})
        if visible:
            groups.append({"label": group_label, "items": visible})
    # ไฮไลต์เฉพาะเมนูที่ URL ตรงกับหน้าปัจจุบันมากที่สุด (เช่น /documents/receive/ ไม่ไฮไลต์ /documents/)
    matches = [
        item for group in groups for item in group["items"]
        if current_path == item["url"] or (item["url"] != "/" and current_path.startswith(item["url"]))
    ]
    if matches:
        max(matches, key=lambda i: len(i["url"]))["active"] = True
    return groups
