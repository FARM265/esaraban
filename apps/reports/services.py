"""
ตัวเลขสำหรับหน้าภาพรวม และข้อมูลติดตามว่าเรื่องค้างอยู่ที่ใคร

ขอบเขต: ผู้บริหาร หัวหน้ากลุ่มงาน และเจ้าหน้าที่สารบรรณ เห็นตัวเลขและรายการของเอกสารที่ตนมีสิทธิ์
ผู้ดูแลระบบและผู้ตรวจสอบเห็นเฉพาะตัวเลขรวมทั้งสำนักงาน ไม่เห็นชื่อเรื่อง (แยกหน้าที่ ไม่มีสิทธิ์อ่านเนื้อหาเอกสาร)
"""
import datetime as dt
from collections import defaultdict

from django.db.models import Avg, Count, DurationField, ExpressionWrapper, F, Q
from django.db.models.functions import TruncMonth
from django.utils import timezone

from apps.accounts.permissions import active_roles
from apps.core.constants import RoleCode
from apps.core.templatetags.thai_date import MONTHS_SHORT
from apps.documents import access
from apps.documents.models import Document, DocumentKind, DocumentStatus
from apps.workflow.models import InstanceStatus, TaskStatus, WorkflowInstance, WorkflowTask

READER_ROLES = {RoleCode.CLERK, RoleCode.HEAD, RoleCode.EXECUTIVE}
REVIEW_STATUSES = [DocumentStatus.IN_REVIEW, DocumentStatus.RETURNED, DocumentStatus.PENDING_SIGNATURE]
ACTION_STATUSES = [DocumentStatus.COMMANDED, DocumentStatus.IN_PROGRESS]
CLOSED_STATUSES = [DocumentStatus.DONE, DocumentStatus.ARCHIVED, DocumentStatus.CANCELLED]


def scope(user):
    """(เอกสารที่นับ, ดูรายการเรื่องได้หรือไม่)"""
    if any(a.role.code in READER_ROLES for a in active_roles(user)):
        return access.visible_documents(user), True
    return Document.objects.all(), False


def holder_label(task):
    if task.assignee_id:
        return task.assignee.display_name_th
    role = RoleCode(task.role).label if task.role else "-"
    return f"{role} {task.department.name_th}" if task.department_id else f"{role} (ทั้งสำนักงาน)"


def _month_starts(today, count):
    months, year, month = [], today.year, today.month
    for _ in range(count):
        months.append(dt.date(year, month, 1))
        month -= 1
        if month == 0:
            year, month = year - 1, 12
    return list(reversed(months))


def _month_key(value):
    if isinstance(value, dt.datetime):
        value = timezone.localtime(value).date() if timezone.is_aware(value) else value.date()
    return value.replace(day=1)


def _bars(rows, label_key, value_key="n"):
    top = max((r[value_key] for r in rows), default=0) or 1
    return [{"label": r[label_key] or "ยังไม่ระบุกลุ่มงาน", "n": r[value_key], "pct": round(r[value_key] * 100 / top)}
            for r in rows]


def dashboard(user, now=None):
    now = now or timezone.now()
    today = timezone.localdate(now)
    month_start = today.replace(day=1)
    qs, can_list = scope(user)
    open_tasks = WorkflowTask.objects.filter(status=TaskStatus.OPEN, instance__document__in=qs)
    overdue_tasks = open_tasks.filter(due_at__lt=now)

    finished = WorkflowInstance.objects.filter(
        status=InstanceStatus.DONE, finished_at__gte=now - dt.timedelta(days=90), document__in=qs
    ).aggregate(avg=Avg(ExpressionWrapper(F("finished_at") - F("started_at"), output_field=DurationField())))["avg"]

    labels = dict(DocumentStatus.choices)
    by_status = [{"label": labels[r["status"]], "n": r["n"]}
                 for r in qs.values("status").annotate(n=Count("pk")).order_by("-n")]
    by_department = list(qs.exclude(status__in=CLOSED_STATUSES).values("owner_department__name_th")
                         .annotate(n=Count("pk")).order_by("-n")[:8])

    months = _month_starts(today, 6)
    start = timezone.make_aware(dt.datetime.combine(months[0], dt.time.min))
    received = defaultdict(int)
    for row in (qs.filter(kind=DocumentKind.INCOMING, created_at__gte=start)
                .annotate(m=TruncMonth("created_at")).values("m").annotate(n=Count("pk"))):
        received[_month_key(row["m"])] += row["n"]
    sent = defaultdict(int)
    for row in (qs.exclude(kind=DocumentKind.INCOMING).filter(registration__issued_at__gte=start)
                .annotate(m=TruncMonth("registration__issued_at")).values("m").annotate(n=Count("pk"))):
        sent[_month_key(row["m"])] += row["n"]
    peak = max([received[m] for m in months] + [sent[m] for m in months] + [1])
    monthly = [{
        "label": f"{MONTHS_SHORT[m.month - 1]} {str(m.year + 543)[2:]}",
        "received": received[m], "sent": sent[m],
        "received_pct": round(received[m] * 100 / peak), "sent_pct": round(sent[m] * 100 / peak),
    } for m in months]

    return {
        "can_list": can_list,
        "kpi": {
            "received_month": qs.filter(kind=DocumentKind.INCOMING, created_at__date__gte=month_start).count(),
            "sent_month": qs.exclude(kind=DocumentKind.INCOMING)
            .filter(registration__issued_at__date__gte=month_start).count(),
            "in_review": qs.filter(status__in=REVIEW_STATUSES).count(),
            "in_progress": qs.filter(status__in=ACTION_STATUSES).count(),
            "overdue_tasks": overdue_tasks.count(),
            "overdue_docs": qs.filter(due_date__lt=today).exclude(status__in=CLOSED_STATUSES).count(),
            "avg_days": round(finished.total_seconds() / 86400, 1) if finished else None,
        },
        "by_status": _bars(by_status, "label"),
        "by_department": _bars(by_department, "owner_department__name_th"),
        "monthly": monthly,
        "overdue_list": tracking_rows(overdue_tasks.order_by("due_at")[:15], now) if can_list else [],
    }


def tracking_rows(tasks, now=None):
    now = now or timezone.now()
    rows = []
    for task in tasks.select_related("instance__document__registration", "assignee", "department"):
        late = now - task.due_at if task.due_at else None
        rows.append({
            "task": task, "document": task.instance.document, "holder": holder_label(task),
            "late_days": late.days if late and late.total_seconds() > 0 else 0,
        })
    return rows


def current_holders(documents, now=None):
    """{document_id: {"holders": [...], "due": datetime|None, "overdue": bool}} ของงานที่เปิดอยู่"""
    now = now or timezone.now()
    result = {}
    tasks = (WorkflowTask.objects.filter(status=TaskStatus.OPEN, instance__document__in=documents)
             .select_related("assignee", "department", "instance").order_by("due_at"))
    for task in tasks:
        entry = result.setdefault(task.instance.document_id, {"holders": [], "due": None, "overdue": False})
        label = holder_label(task)
        if label not in entry["holders"]:
            entry["holders"].append(label)
        if task.due_at and (entry["due"] is None or task.due_at < entry["due"]):
            entry["due"] = task.due_at
        entry["overdue"] = entry["overdue"] or bool(task.due_at and task.due_at < now)
    return result


def search(user, params, today=None):
    """ค้นหาเอกสารที่ผู้ใช้มีสิทธิ์ params คือ cleaned_data ของ SearchForm"""
    from apps.workflow.services import actionable_tasks

    today = today or timezone.localdate()
    qs = access.visible_documents(user).select_related("registration", "owner_department")
    q = params.get("q")
    if q:
        qs = qs.filter(
            Q(subject__icontains=q) | Q(registration__display_no__icontains=q) | Q(source_doc_no__icontains=q)
            | Q(source_org__icontains=q) | Q(recipient__icontains=q) | Q(note__icontains=q)
            | Q(letter__body__icontains=q)
        )
    for field in ("kind", "status"):
        if params.get(field):
            qs = qs.filter(**{field: params[field]})
    if params.get("department"):
        qs = qs.filter(owner_department=params["department"])
    if params.get("date_from"):
        qs = qs.filter(created_at__date__gte=params["date_from"])
    if params.get("date_to"):
        qs = qs.filter(created_at__date__lte=params["date_to"])
    if params.get("urgent"):
        qs = qs.filter(urgency__gt=0)
    if params.get("mine"):
        qs = qs.filter(pk__in=actionable_tasks(user).values("instance__document"))
    if params.get("overdue"):
        late_tasks = WorkflowTask.objects.filter(status=TaskStatus.OPEN, due_at__lt=timezone.now())
        qs = qs.filter(
            Q(pk__in=late_tasks.values("instance__document"))
            | (Q(due_date__lt=today) & ~Q(status__in=CLOSED_STATUSES))
        )
    return qs.distinct().order_by("-created_at")
