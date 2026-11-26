from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.security import client_ip
from apps.documents import access
from apps.documents.models import Document, DocumentStatus

from . import services
from .forms import ArchiveForm, ReleaseForm
from .models import ArchiveRecord


def index(request):
    docs = access.visible_documents(request.user).filter(status=DocumentStatus.ARCHIVED)
    records = ArchiveRecord.objects.filter(released_at__isnull=True, document__in=docs).select_related("document__registration", "document__owner_department", "archived_by")
    q = request.GET.get("q", "").strip()
    folder = request.GET.get("folder", "").strip()
    year = request.GET.get("year", "").strip()
    due = request.GET.get("due") == "1"
    if q:
        records = records.filter(Q(document__subject__icontains=q) | Q(document__registration__display_no__icontains=q)
                                 | Q(document__source_org__icontains=q) | Q(note__icontains=q))
    if folder:
        records = records.filter(folder=folder)
    if year.isdigit():
        records = records.filter(archived_at__year=int(year) - 543)
    today = timezone.localdate()
    if due:
        records = records.filter(keep_until__lte=today)
    page = Paginator(records.order_by("folder", "-archived_at"), 25).get_page(request.GET.get("page"))
    query = request.GET.copy()
    query.pop("page", None)
    years = sorted({d.year + 543 for d in ArchiveRecord.objects.filter(document__in=docs).dates("archived_at", "year")},
                   reverse=True)
    return render(request, "archive/index.html", {
        "page": page, "q": q, "folder": folder, "year": year, "due": due, "today": today,
        "folders": services.folders(), "years": years, "querystring": query.urlencode(),
        "due_count": ArchiveRecord.objects.filter(released_at__isnull=True, document__in=docs,
                                                  keep_until__lte=today).count(),
    })


def _document(request, pk):
    document = get_object_or_404(Document, pk=pk)
    if not access.can_view(request.user, document):
        raise Http404
    return document


@require_POST
def archive(request, pk):
    document = _document(request, pk)
    form = ArchiveForm(request.POST)
    if not form.is_valid():
        messages.error(request, "ยังไม่ได้จัดเก็บ กรุณาเลือกหมวด/แฟ้ม (หรือพิมพ์ชื่อหมวดใหม่) และอายุการเก็บ")
        return redirect("documents:detail", pk=document.pk)
    try:
        data = {k: form.cleaned_data[k] for k in ("folder", "retention_years", "note")}
        record = services.archive(document, request.user, ip=client_ip(request), **data)
    except PermissionDenied:
        messages.error(request, "จัดเก็บเรื่องนี้ไม่ได้ (ยังไม่เสร็จ อยู่ระหว่างเสนอ หรือท่านไม่มีสิทธิ์)")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"จัดเก็บเข้าแฟ้ม {record.folder} แล้ว เอกสารนี้อ่านได้อย่างเดียว")
    return redirect("documents:detail", pk=document.pk)


@require_POST
def release(request, pk):
    document = _document(request, pk)
    form = ReleaseForm(request.POST)
    if not form.is_valid():
        messages.error(request, "กรุณาระบุเหตุผลที่นำออกจากคลัง")
        return redirect("documents:detail", pk=document.pk)
    try:
        services.release(document, request.user, reason=form.cleaned_data["reason"], ip=client_ip(request))
    except PermissionDenied:
        messages.error(request, "ท่านไม่มีสิทธิ์นำเรื่องนี้ออกจากคลัง")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, "นำออกจากคลังแล้ว เรื่องกลับเป็นสถานะเดิม")
    return redirect("documents:detail", pk=document.pk)
