"""
ระบบสิทธิ์ตามบทบาท (RBAC)

แต่ละ "ความสามารถ" (capability) ระบุว่าบทบาทใดทำได้ ถ้าบทบาทมีขอบเขตกลุ่มงาน
จะใช้ได้เฉพาะกลุ่มงานนั้นและกลุ่มงานย่อย ถ้าไม่ระบุกลุ่มงาน (ทั้งสำนักงาน) ใช้ได้ทุกกลุ่มงาน

สิทธิ์เปิดอ่านเอกสารรายฉบับ (ชั้นความลับ, ACL) จะเพิ่มในขั้นตอนที่ 6
ผู้ดูแลระบบ (ADMIN) จัดการผู้ใช้ได้ แต่ไม่ได้สิทธิ์อ่านเอกสารโดยอัตโนมัติ (แยกหน้าที่)
"""
from functools import wraps

from django.core.exceptions import PermissionDenied

from apps.core.constants import RoleCode as R

CAPABILITIES = {
    # ผู้ใช้และระบบ
    "manage_users": {R.ADMIN},
    "view_system_status": {R.ADMIN},
    "view_audit": {R.ADMIN, R.AUDITOR},
    # ทะเบียนเลข
    "manage_registers": {R.ADMIN},
    "manage_workflows": {R.ADMIN},
    "view_registry": {R.CLERK, R.HEAD, R.EXECUTIVE, R.AUDITOR, R.ADMIN},
    # งานสารบรรณ (ใช้ในขั้นตอนที่ 6–8)
    "register_documents": {R.CLERK},
    "create_documents": {R.CLERK, R.STAFF, R.HEAD, R.EXECUTIVE},
    "review_documents": {R.HEAD},
    "command_documents": {R.EXECUTIVE},
    "sign_documents": {R.EXECUTIVE, R.HEAD},
    "endorse_documents": {R.EXECUTIVE, R.HEAD, R.CLERK},
    "archive_documents": {R.CLERK},
    "view_reports": {R.EXECUTIVE, R.HEAD, R.AUDITOR, R.ADMIN},
}

CAPABILITY_LABELS = {
    "manage_users": "จัดการผู้ใช้และสิทธิ์",
    "view_system_status": "ดูสถานะระบบ",
    "view_audit": "ดู Audit Log",
    "manage_registers": "ตั้งค่าชุดทะเบียน",
    "manage_workflows": "ตั้งค่าเส้นทางการเสนอ",
    "view_registry": "ดูทะเบียนเลขหนังสือ",
    "register_documents": "ลงทะเบียนรับ-ส่งหนังสือ",
    "create_documents": "สร้างหนังสือ",
    "review_documents": "พิจารณาเสนอหนังสือ",
    "command_documents": "สั่งการ",
    "sign_documents": "ลงนามเอกสาร",
    "endorse_documents": "สั่งการ/เกษียน",
    "archive_documents": "จัดเก็บเอกสารเข้าคลัง",
    "view_reports": "ดูรายงาน",
}


def active_roles(user):
    """บทบาทที่มีผลวันนี้ เก็บผลไว้บน object ผู้ใช้เพื่อไม่ query ซ้ำในคำขอเดียวกัน"""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return []
    cached = getattr(user, "_es_active_roles", None)
    if cached is None:
        from .models import UserRole

        cached = list(
            UserRole.objects.active().filter(user=user).select_related("role", "department")
        )
        user._es_active_roles = cached
    return cached


def role_codes(user):
    codes = {a.role.code for a in active_roles(user)}
    if getattr(user, "is_superuser", False) and user.is_active:
        codes.add(R.ADMIN)
    return codes


def has_capability(user, capability, department=None):
    if capability not in CAPABILITIES:
        raise ValueError(f"ไม่รู้จักสิทธิ์ {capability}")
    allowed = CAPABILITIES[capability]
    if getattr(user, "is_superuser", False) and user.is_active and R.ADMIN in allowed:
        return True
    target_ids = department.ancestor_ids() if department is not None else None
    for assignment in active_roles(user):
        if assignment.role.code not in allowed:
            continue
        if target_ids is None or assignment.department_id is None or assignment.department_id in target_ids:
            return True
    return False


def capability_required(capability):
    """decorator สำหรับ view ผู้ใช้ที่ไม่มีสิทธิ์จะได้หน้า 403"""

    def decorator(view_func):
        @wraps(view_func)
        def wrapper(request, *args, **kwargs):
            if not has_capability(request.user, capability):
                raise PermissionDenied
            return view_func(request, *args, **kwargs)

        return wrapper

    return decorator
