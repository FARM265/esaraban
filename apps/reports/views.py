from io import BytesIO

from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied
from django.core.paginator import Paginator
from django.http import FileResponse
from django.shortcuts import render
from django.utils import timezone

from apps.accounts.permissions import active_roles, capability_required, has_capability
from apps.accounts.security import client_ip
from apps.core.constants import RoleCode

from . import exports, registers, services
from .forms import ReportForm, SearchForm


@capability_required("view_reports")
def dashboard(request):
    from apps.workflow.services import actionable_tasks

    context = services.dashboard(request.user)
    context["my_tasks"] = actionable_tasks(request.user).count()
    context["today"] = timezone.localdate()
    return render(request, "reports/dashboard.html", context)


def search(request):
    form = SearchForm(request.GET or None)
    searched = form.is_bound and form.is_valid()
    qs = services.search(request.user, form.cleaned_data if searched else {})
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    holders = services.current_holders([d.pk for d in page])
    rows = [{"doc": d, "track": holders.get(d.pk)} for d in page]
    query = request.GET.copy()
    query.pop("page", None)
    roles = {a.role.code for a in active_roles(request.user)}
    can_read = bool(roles & {RoleCode.CLERK, RoleCode.HEAD, RoleCode.EXECUTIVE, RoleCode.STAFF})
    return render(request, "reports/search.html", {
        "form": form, "page": page, "rows": rows, "querystring": query.urlencode(),
        "can_read": can_read or page.paginator.count > 0, "searched": searched,
    })


MAX_PDF_ROWS = 1500


def can_export(user):
    return has_capability(user, "view_reports") or has_capability(user, "register_documents")


def reports(request):
    if not can_export(request.user):
        raise PermissionDenied
    today = timezone.localdate()
    initial = {"kind": "incoming", "date_from": today.replace(day=1), "date_to": today}
    form = ReportForm(request.GET or None, initial=initial)
    if request.GET.get("format") and form.is_valid():
        data = form.cleaned_data
        report = registers.build(
            data["kind"], request.user, date_from=data["date_from"], date_to=data["date_to"],
            department=data["department"], overdue_only=data["overdue_only"],
        )
        fmt = data["format"]
        if fmt == "pdf" and len(report.rows) > MAX_PDF_ROWS:
            messages.error(request, f"รายงานมี {len(report.rows):,} รายการ เกิน {MAX_PDF_ROWS:,} รายการสำหรับ PDF "
                                    "กรุณาเลือกช่วงวันที่ให้สั้นลง หรือดาวน์โหลดเป็น Excel")
            return render(request, "reports/reports.html", {"form": form})
        from apps.audit import services as audit

        audit.record("DOCUMENT", "REPORT_EXPORTED", f"ดาวน์โหลดรายงาน{report.title} ({fmt.upper()})",
                     actor=request.user, ip=client_ip(request), rows=len(report.rows),
                     date_from=data["date_from"], date_to=data["date_to"])
        name = f"{report.title} {data['date_from'].isoformat()} ถึง {data['date_to'].isoformat()}"
        if fmt == "pdf":
            body = exports.to_pdf(report.title, report.subtitle, report.columns, report.rows,
                                  regular_font=settings.ESARABAN_TEXT_FONT, bold_font=settings.ESARABAN_TEXT_FONT_BOLD,
                                  footer=f"{settings.ESARABAN_ORG_NAME} · E-Saraban")
            content_type = "application/pdf"
        else:
            body = exports.to_xlsx(report.title, report.subtitle, report.columns, report.rows)
            content_type = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
        response = FileResponse(BytesIO(body), as_attachment=True, filename=f"{name}.{fmt}", content_type=content_type)
        response["Cache-Control"] = "private, no-store"
        return response
    return render(request, "reports/reports.html", {"form": form})
