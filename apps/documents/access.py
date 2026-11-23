"""
สิทธิ์เข้าถึงเอกสารรายฉบับ

ผู้ใช้เห็นเอกสารได้เมื่อผ่านทั้ง 2 เงื่อนไข
1. ชั้นความลับของเอกสารไม่เกินระดับสิทธิ์ของผู้ใช้ (clearance_level)
2. อย่างน้อยหนึ่งข้อ:
   - เป็นผู้ลงทะเบียน/สร้างเอกสารนั้น
   - มีบทบาทเจ้าหน้าที่สารบรรณ หัวหน้ากลุ่มงาน หรือผู้บริหาร ที่ขอบเขตครอบคลุมกลุ่มงานเจ้าของเรื่อง
     (บทบาทแบบทั้งสำนักงาน = เห็นทุกกลุ่มงาน รวมถึงเอกสารที่ยังไม่ระบุกลุ่มงาน)
   - มีบทบาทเจ้าหน้าที่ทั่วไป และเอกสารเป็นของกลุ่มงานที่ตนสังกัด

ผู้ดูแลระบบและผู้ตรวจสอบไม่ได้สิทธิ์อ่านเนื้อเอกสารโดยอัตโนมัติ (แยกหน้าที่)
ขั้นตอนที่ 7 จะเพิ่มสิทธิ์จากการถูกมอบหมายใน workflow
"""
from django.db.models import Q

from apps.accounts.models import department_with_descendants as _with_descendants
from apps.accounts.permissions import active_roles, has_capability
from apps.core.constants import RoleCode

from .models import LOCKED_STATUSES, Document

SCOPED_VIEW_ROLES = {RoleCode.CLERK, RoleCode.HEAD, RoleCode.EXECUTIVE}


def visible_department_ids(user):
    """None = ทุกกลุ่มงาน, set() = ไม่มี, หรือชุด id ของกลุ่มงานที่มองเห็น"""
    scoped = set()
    for assignment in active_roles(user):
        code = assignment.role.code
        if code in SCOPED_VIEW_ROLES:
            if assignment.department_id is None:
                return None
            scoped.add(assignment.department_id)
        elif code == RoleCode.STAFF and user.department_id:
            scoped.add(user.department_id)
    return _with_descendants(scoped) if scoped else set()


def visible_documents(user, queryset=None):
    qs = Document.objects.all() if queryset is None else queryset
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return qs.none()
    qs = qs.filter(secrecy__lte=user.clearance_level)
    dept_ids = visible_department_ids(user)
    if dept_ids is None:
        return qs
    # เอกสารที่ผู้ใช้ได้รับงานหรือเคยดำเนินการใน workflow (รวมงานที่ทำแทนผู้มอบหมาย)
    from apps.workflow.services import involved_document_ids

    return qs.filter(
        Q(created_by=user) | Q(owner_department_id__in=dept_ids) | Q(pk__in=involved_document_ids(user))
    )


def can_view(user, document):
    return visible_documents(user).filter(pk=document.pk).exists()


def can_edit(user, document):
    if document.status in LOCKED_STATUSES or not can_view(user, document):
        return False
    return has_capability(user, "register_documents", document.owner_department)
