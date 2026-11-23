import io

from django.conf import settings
from django.contrib import messages
from django.core.paginator import Paginator
from django.db.models import Q
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache

from apps.accounts.permissions import capability_required
from apps.accounts.security import client_ip
from apps.registry.services import peek_next_number

from . import access, services, storage
from .forms import DocumentEditForm, ReceiveForm
from .models import LOCKED_STATUSES, Attachment, Document, DocumentEvent, DocumentKind, DocumentStatus


@capability_required("register_documents")
def receive(request):
    form = ReceiveForm(request.POST or None, request.FILES or None, user=request.user)
    if request.method == "POST" and form.is_valid():
        document = services.register_incoming(
            book=form.cleaned_data["book"],
            data=form.document_data(),
            main_file=form.cleaned_data["main_file"],
            extra_files=form.cleaned_data["extra_files"],
            user=request.user,
            ip=client_ip(request),
        )
        messages.success(request, f"ลงทะเบียนรับแล้ว เลขรับ {document.registration.display_no}")
        return redirect("documents:detail", pk=document.pk)

    book = form.fields["book"].queryset.first()
    return render(
        request,
        "documents/receive.html",
        {"form": form, "next_number": peek_next_number(book) if book else None},
    )


def document_list(request):
    qs = access.visible_documents(request.user).select_related("registration", "owner_department")
    q = request.GET.get("q", "").strip()
    kind = request.GET.get("kind", "")
    status = request.GET.get("status", "")
    if q:
        qs = qs.filter(
            Q(subject__icontains=q)
            | Q(registration__display_no__icontains=q)
            | Q(source_doc_no__icontains=q)
            | Q(source_org__icontains=q)
        )
    if kind in DocumentKind.values:
        qs = qs.filter(kind=kind)
    if status in DocumentStatus.values:
        qs = qs.filter(status=status)
    page = Paginator(qs, 25).get_page(request.GET.get("page"))
    return render(
        request,
        "documents/list.html",
        {
            "page": page, "q": q, "kind": kind, "status": status,
            "kinds": DocumentKind.choices, "statuses": DocumentStatus.choices,
        },
    )


def _can_calendar(user):
    from .calendar_views import can_use_calendar

    return can_use_calendar(user)


def _get_visible(request, pk):
    document = get_object_or_404(Document.objects.select_related("registration", "owner_department", "created_by"), pk=pk)
    if not access.can_view(request.user, document):
        raise Http404  # ไม่บอกว่ามีเอกสารนี้อยู่ ถ้าไม่มีสิทธิ์
    return document


def document_detail(request, pk):
    from apps.archive.panel import context_for as archive_context
    from apps.letters.panel import context_for as letter_context
    from apps.signatures.panel import context_for as signing_context
    from apps.workflow.panel import context_for

    document = _get_visible(request, pk)
    attachments = list(document.attachments.select_related("uploaded_by"))
    context = {
        "doc": document,
        "attachments": attachments,
        # แสดงไฟล์ล่าสุดในหน้าเอกสารทันที ไม่ต้องกดเปิดดู
        "preview": max(attachments, key=lambda a: (a.uploaded_at, a.pk), default=None),
        "events": document.events.select_related("actor")[:50],
        "can_edit": access.can_edit(request.user, document),
        "can_calendar": _can_calendar(request.user),
    }
    context.update(context_for(request.user, document))
    context.update(signing_context(request.user, document))
    context.update(letter_context(request.user, document))
    context.update(archive_context(request.user, document))
    if context["letter"]:
        context["can_edit"] = False  # หนังสือจากแม่แบบแก้ไขผ่าน "แก้ไขร่าง"
    return render(request, "documents/detail.html", context)


def document_edit(request, pk):
    document = _get_visible(request, pk)
    if not access.can_edit(request.user, document) or hasattr(document, "letter"):
        raise Http404
    form = DocumentEditForm(request.POST or None, instance=document, user=request.user)
    if request.method == "POST" and form.is_valid():
        changed = services.update_document(document, form, request.user, client_ip(request))
        messages.success(request, "บันทึกการแก้ไขแล้ว" if changed else "ไม่มีข้อมูลที่เปลี่ยนแปลง")
        return redirect("documents:detail", pk=document.pk)
    return render(request, "documents/edit.html", {"doc": document, "form": form})


def attachment_viewer(request, pk):
    """หน้าดู PDF ด้วย PDF.js พร้อมความเห็น (ตัวไฟล์โหลดจาก attachment_file ซึ่งตรวจสิทธิ์และบันทึกประวัติ)"""
    from apps.signatures import services as signing

    attachment = get_object_or_404(Attachment.objects.select_related("document__registration"), pk=pk)
    document = attachment.document
    if not access.can_view(request.user, document):
        raise Http404
    from apps.annotations import services as endorsing
    from apps.annotations.models import INK_COLORS, INK_SIZES

    from apps.signatures import digital

    can_sign = signing.can_sign(request.user, document)
    can_endorse = endorsing.can_endorse(request.user, document)
    # ไฟล์ที่มีลายมือชื่อดิจิทัล: ตรวจทุกครั้งที่เปิด และห้ามเขียนทับเนื้อหา (จะทำให้ลายมือชื่อเดิมเสีย)
    pdf = storage.read_decrypted(attachment.storage_key, attachment.sha256)
    has_digital = digital.has_digital_signatures(pdf)
    sig_checks = digital.verify_bytes(pdf) if has_digital else []
    for index, check in enumerate(sig_checks):
        later = sig_checks[index + 1:]
        check.later_signed = bool(later) and later[-1].covers_whole_file and all(c.ok for c in later)
    if has_digital:
        can_endorse = False
    # หนังสือจากแม่แบบรู้ตำแหน่งลงนามอยู่แล้ว ตัวดูจึงวางลายเซ็นให้ตรงที่ทันทีเมื่อกด "วางลายเซ็น"
    sign_default = ""
    letter = getattr(document, "letter", None) if attachment.is_main else None
    anchor = letter.sign_anchor if letter else None
    if can_sign and anchor and (attachment.page_count or 0) >= anchor.get("page", 1):
        sign_default = f'{anchor["page"]},{anchor["x"]},{anchor["y"]},{anchor["w"]}'
    return render(
        request,
        "documents/viewer.html",
        {
            "can_endorse": can_endorse,
            "ink_colors": [(key, label, hex_) for key, (label, hex_) in INK_COLORS.items()],
            "ink_sizes": [(key, label) for key, (label, _pt) in INK_SIZES.items()],
            "doc": document,
            "attachment": attachment,
            "can_annotate": document.status not in LOCKED_STATUSES,
            "can_sign": can_sign,
            "sign_has_image": can_sign and signing.active_signature_image(request.user) is not None,
            "sign_require_otp": settings.ESARABAN_SIGN_REQUIRE_OTP,
            "start_sign": request.GET.get("sign") == "1",
            "sign_default": sign_default,
            "has_digital": has_digital,
            "sig_checks": sig_checks,
            "digital_enabled": digital.enabled(),
        },
    )


@never_cache
def attachment_file(request, pk):
    """ส่งไฟล์ที่ถอดรหัสแล้ว ตรวจสิทธิ์และบันทึกประวัติทุกครั้ง  ?download=1 = ดาวน์โหลด, ไม่ใส่ = เปิดดู"""
    attachment = get_object_or_404(Attachment.objects.select_related("document"), pk=pk)
    if not access.can_view(request.user, attachment.document):
        raise Http404
    download = request.GET.get("download") == "1"
    data = storage.read_decrypted(attachment.storage_key, attachment.sha256)
    services.log_event(
        attachment.document, request.user,
        DocumentEvent.Action.DOWNLOADED if download else DocumentEvent.Action.VIEWED,
        client_ip(request), file=attachment.original_name,
    )
    response = FileResponse(
        io.BytesIO(data), as_attachment=download, filename=attachment.original_name, content_type="application/pdf"
    )
    response["Cache-Control"] = "private, no-store"
    return response
