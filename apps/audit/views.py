import datetime as dt

from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.shortcuts import redirect, render
from django.views.decorators.http import require_POST

from apps.accounts.permissions import capability_required
from apps.accounts.security import client_ip

from . import services
from .models import AuditEntry, Category


def _date(value):
    try:
        return dt.date.fromisoformat(value) if value else None
    except ValueError:
        return None


def _filtered(request):
    qs = AuditEntry.objects.all()
    q = request.GET.get("q", "").strip()
    category = request.GET.get("category", "")
    date_from, date_to = _date(request.GET.get("from")), _date(request.GET.get("to"))
    if q:
        qs = qs.filter(Q(summary__icontains=q) | Q(actor_label__icontains=q) | Q(action__icontains=q)
                       | Q(ip_address__startswith=q) | Q(target_id=q))
    if category in Category.values:
        qs = qs.filter(category=category)
    if date_from:
        qs = qs.filter(at__date__gte=date_from)
    if date_to:
        qs = qs.filter(at__date__lte=date_to)
    return qs, q, category


@capability_required("view_audit")
def index(request):
    qs, q, category = _filtered(request)
    page = Paginator(qs.select_related("actor"), 50).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    return render(request, "audit/index.html", {
        "page": page, "q": q, "category": category, "categories": Category.choices,
        "date_from": request.GET.get("from", ""), "date_to": request.GET.get("to", ""),
        "querystring": query.urlencode(), "total": AuditEntry.objects.count(),
    })


@require_POST
@capability_required("view_audit")
def verify(request):
    result = services.verify()
    services.record(
        "SETTINGS", "AUDIT_VERIFIED", f"ตรวจความครบถ้วนของ Audit Log: {'ผ่าน' if result.ok else 'ไม่ผ่าน'}",
        actor=request.user, ip=client_ip(request), checked=result.checked, ok=result.ok, problem_seq=result.problem_seq,
    )
    if result.ok:
        messages.success(request, f"ตรวจแล้ว {result.checked:,} รายการ ครบถ้วน ไม่พบการแก้ไข ลบ หรือแทรกรายการ")
    else:
        messages.error(request, f"พบความผิดปกติที่รายการลำดับ {result.problem_seq}: {result.problem} "
                                f"(ตรวจผ่าน {result.checked:,} รายการก่อนหน้า) กรุณาแจ้งผู้รับผิดชอบระบบ")
    return redirect("audit:index")


MAX_EXPORT_ROWS = 50000


@capability_required("view_audit")
def export(request):
    """Audit Log ตามเงื่อนไขที่ค้นหาอยู่ เป็น Excel (ใหม่สุดก่อน ไม่เกิน 50,000 รายการ)"""
    from io import BytesIO

    from django.http import FileResponse
    from django.utils import timezone

    from apps.core.templatetags.thai_date import thai_datetime
    from apps.reports.exports import to_xlsx

    qs, _, _ = _filtered(request)
    total = qs.count()
    entries = list(qs.order_by("-seq")[:MAX_EXPORT_ROWS])
    rows = [[e.seq, thai_datetime(e.at), e.actor_label, e.get_category_display(), e.summary, e.action,
             e.ip_address or "", e.hash] for e in entries]
    subtitle = f"ดาวน์โหลดเมื่อ {thai_datetime(timezone.now())} · {len(rows):,} รายการ"
    if total > len(rows):
        subtitle += f" (จากทั้งหมด {total:,} รายการ แสดงเฉพาะล่าสุด)"
    body = to_xlsx("Audit Log", subtitle, [("ลำดับ", 0.7), ("เวลา", 1.6), ("ผู้ใช้", 2), ("หมวด", 1.1),
                                           ("รายการ", 4), ("รหัส", 1.5), ("IP", 1.2), ("hash", 2.5)], rows)
    services.record("SETTINGS", "AUDIT_EXPORTED", f"ดาวน์โหลด Audit Log {len(rows):,} รายการ",
                    actor=request.user, ip=client_ip(request), filters=request.GET.urlencode())
    response = FileResponse(BytesIO(body), as_attachment=True,
                            filename=f"audit-log-{timezone.localdate().isoformat()}.xlsx",
                            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
    response["Cache-Control"] = "private, no-store"
    return response
