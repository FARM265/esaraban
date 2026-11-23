"""
รายงานที่ดาวน์โหลดได้ (ทะเบียนหนังสือรับ ทะเบียนหนังสือส่ง เรื่องค้าง/เกินกำหนด)

ทุกรายงานดึงจากเอกสารที่ผู้ใช้มีสิทธิ์เห็นเท่านั้น เลขที่ออกโดยไม่มีเอกสารในระบบ (ขอเลขจากหน้าทะเบียน)
แสดงเฉพาะผู้มีสิทธิ์ลงทะเบียนหนังสือ (เจ้าหน้าที่สารบรรณ)
"""
from dataclasses import dataclass

from django.db.models import Q
from django.utils import timezone

from apps.accounts.permissions import has_capability
from apps.core.templatetags.thai_date import thai_date
from apps.documents import access
from apps.documents.models import DocumentKind
from apps.registry.models import IssuedNumber, RegisterType

from .services import CLOSED_STATUSES, current_holders


@dataclass
class Report:
    title: str
    subtitle: str
    columns: list
    rows: list


KINDS = [
    ("incoming", "ทะเบียนหนังสือรับ"),
    ("outgoing", "ทะเบียนหนังสือส่ง (หนังสือภายนอก บันทึกข้อความ คำสั่ง ประกาศ)"),
    ("pending", "เรื่องค้างดำเนินการ / เกินกำหนด"),
]


def _period(date_from, date_to):
    return f"ระหว่างวันที่ {thai_date(date_from, 'full')} ถึง {thai_date(date_to, 'full')}"


def incoming(user, date_from, date_to, department=None):
    qs = (access.visible_documents(user).filter(kind=DocumentKind.INCOMING, registration__isnull=False,
                                                created_at__date__range=(date_from, date_to))
          .select_related("registration", "owner_department").order_by("registration__year_be", "registration__running_no"))
    if department:
        qs = qs.filter(owner_department=department)
    rows = [[
        d.registration.display_no, thai_date(d.created_at), d.source_doc_no, thai_date(d.source_doc_date),
        d.source_org, d.owner_department.name_th if d.owner_department else "", d.subject, d.get_status_display(),
        "ยกเลิกเลข" if d.registration.is_voided else d.note,
    ] for d in qs]
    return Report(
        "ทะเบียนหนังสือรับ", f"{_period(date_from, date_to)} · {len(rows)} รายการ",
        [("เลขทะเบียนรับ", 1.1), ("วันที่รับ", 1.3), ("ที่", 1.4), ("ลงวันที่", 1.3), ("จาก", 2),
         ("ถึง", 1.6), ("เรื่อง", 4), ("การปฏิบัติ", 1.3), ("หมายเหตุ", 1.4)],
        rows,
    )


SEND_TYPES = [RegisterType.SEND, RegisterType.INTERNAL, RegisterType.ORDER, RegisterType.ANNOUNCE]


def outgoing(user, date_from, date_to, department=None):
    visible = access.visible_documents(user).values("pk")
    numbers = (IssuedNumber.objects.filter(book__register_type__in=SEND_TYPES,
                                           issued_at__date__range=(date_from, date_to))
               .select_related("book", "document__owner_department").order_by("book__code", "year_be", "running_no"))
    own_numbers = Q(document__isnull=True) if has_capability(user, "register_documents") else Q(pk__in=[])
    numbers = numbers.filter(Q(document__in=visible) | own_numbers)
    if department:
        numbers = numbers.filter(document__owner_department=department)
    rows = []
    for n in numbers:
        doc = getattr(n, "document", None)
        rows.append([
            n.display_no, thai_date(n.issued_at), n.book.get_register_type_display(),
            doc.owner_department.name_th if doc and doc.owner_department else "",
            (doc.recipient if doc else n.recipient) or "", doc.subject if doc else n.subject,
            doc.get_status_display() if doc else "ขอเลขโดยไม่มีเอกสารในระบบ",
            f"ยกเลิก: {n.void_reason}" if n.is_voided else "",
        ])
    return Report(
        "ทะเบียนหนังสือส่ง", f"{_period(date_from, date_to)} · {len(rows)} รายการ",
        [("ที่", 1.4), ("ลงวันที่", 1.3), ("ประเภท", 1.3), ("จาก", 1.6), ("ถึง", 2.2), ("เรื่อง", 4),
         ("การปฏิบัติ", 1.4), ("หมายเหตุ", 1.6)],
        rows,
    )


def pending(user, date_from, date_to, department=None, overdue_only=False):
    now = timezone.now()
    today = timezone.localdate(now)
    qs = (access.visible_documents(user).exclude(status__in=[*CLOSED_STATUSES, "DRAFT"])
          .filter(created_at__date__range=(date_from, date_to))
          .select_related("registration", "owner_department").order_by("created_at"))
    if department:
        qs = qs.filter(owner_department=department)
    docs = list(qs)
    holders = current_holders([d.pk for d in docs], now)
    rows = []
    for d in docs:
        track = holders.get(d.pk) or {}
        due = track.get("due")
        due_date = timezone.localdate(due) if due else d.due_date
        late = (today - due_date).days if due_date and due_date < today else 0
        overdue = track.get("overdue") or late > 0
        if overdue_only and not overdue:
            continue
        rows.append([
            d.registration.display_no if d.registration_id else "", d.subject, d.get_status_display(),
            ", ".join(track.get("holders", [])) or "-", thai_date(d.created_at), thai_date(due_date) if due_date else "-",
            f"{late} วัน" if late else ("เกินกำหนด" if overdue else ""),
        ])
    title = "เรื่องเกินกำหนด" if overdue_only else "เรื่องค้างดำเนินการ"
    return Report(
        title, f"เรื่องที่รับ/สร้าง{_period(date_from, date_to)} สถานะ ณ {thai_date(today, 'full')} · {len(rows)} รายการ",
        [("เลขทะเบียน", 1.2), ("เรื่อง", 4), ("สถานะ", 1.4), ("อยู่ที่", 2.2), ("รับเมื่อ", 1.3),
         ("กำหนด", 1.3), ("เกินกำหนด", 1.1)],
        rows,
    )


def build(kind, user, *, date_from, date_to, department=None, overdue_only=False):
    if kind == "incoming":
        return incoming(user, date_from, date_to, department)
    if kind == "outgoing":
        return outgoing(user, date_from, date_to, department)
    if kind == "pending":
        return pending(user, date_from, date_to, department, overdue_only)
    raise ValueError("ไม่รู้จักรายงานนี้")
