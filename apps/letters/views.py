from io import BytesIO

from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import FileResponse, Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.accounts.permissions import capability_required
from apps.accounts.security import client_ip
from apps.documents import access
from apps.documents.models import Document

from . import services
from .forms import IssueForm, LetterForm, LetterheadForm
from .models import Letterhead


@capability_required("create_documents")
def create(request):
    form = LetterForm(request.POST or None, user=request.user, initial=None if request.method == "POST" else {
        "kind": request.GET.get("kind", "OUTGOING")})
    if request.method == "POST":
        if form.is_valid():
            try:
                document = services.create_letter(
                    kind=form.cleaned_data["kind"], document_data=form.document_data(),
                    content_data=form.content_data(), user=request.user, ip=client_ip(request),
                )
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, "สร้างร่างหนังสือแล้ว ตรวจไฟล์ร่างได้ในหน้านี้")
                return redirect("documents:detail", pk=document.pk)
        else:
            messages.error(request, "ยังไม่ได้บันทึก กรุณาตรวจข้อมูลที่มีเครื่องหมายสีแดง")
    return render(request, "letters/form.html", {"form": form, "editing": None})


def _letter_or_404(request, pk):
    document = get_object_or_404(Document.objects.select_related("letter", "owner_department"), pk=pk)
    if not access.can_view(request.user, document) or not services.is_letter(document):
        raise Http404
    return document


def revise(request, pk):
    document = _letter_or_404(request, pk)
    if not services.can_revise(request.user, document):
        messages.error(request, "แก้ไขร่างนี้ไม่ได้ (ออกเลขแล้ว อยู่ระหว่างเสนอ หรือท่านไม่มีสิทธิ์)")
        return redirect("documents:detail", pk=document.pk)
    form = LetterForm(request.POST or None, user=request.user, document=document)
    if request.method == "POST":
        if form.is_valid():
            try:
                services.revise_letter(
                    document=document, document_data=form.document_data(), content_data=form.content_data(),
                    user=request.user, ip=client_ip(request),
                )
            except PermissionDenied:
                messages.error(request, "แก้ไขร่างนี้ไม่ได้แล้ว")
            except ValidationError as exc:
                messages.error(request, " ".join(exc.messages))
            else:
                messages.success(request, "บันทึกการแก้ไขแล้ว ระบบสร้างไฟล์ร่างฉบับใหม่ ฉบับเดิมยังเก็บไว้")
                return redirect("documents:detail", pk=document.pk)
        else:
            messages.error(request, "ยังไม่ได้บันทึก กรุณาตรวจข้อมูลที่มีเครื่องหมายสีแดง")
    return render(request, "letters/form.html", {"form": form, "editing": document})


@require_POST
def issue(request, pk):
    document = _letter_or_404(request, pk)
    if not services.can_issue(request.user, document):
        messages.error(request, "ออกเลขหนังสือนี้ไม่ได้ (ออกเลขแล้ว อยู่ระหว่างเสนอ หรือท่านไม่มีสิทธิ์)")
        return redirect("documents:detail", pk=document.pk)
    form = IssueForm(request.POST, books=services.books_for(document))
    if not form.is_valid():
        messages.error(request, "กรุณาเลือกชุดทะเบียน")
        return redirect("documents:detail", pk=document.pk)
    try:
        number = services.issue_number(
            document=document, book=form.cleaned_data["book"], user=request.user, ip=client_ip(request)
        )
    except PermissionDenied:
        messages.error(request, "ออกเลขหนังสือนี้ไม่ได้แล้ว")
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
    else:
        messages.success(request, f"ออกเลข {number.display_no} แล้ว ระบบประทับเลขที่และวันที่ลงไฟล์ฉบับใหม่")
    return redirect("documents:detail", pk=document.pk)


@never_cache
def download_docx(request, pk):
    """ดาวน์โหลดหนังสือเป็น Word ผู้ที่เห็นเอกสารได้ดาวน์โหลดได้ และบันทึกในประวัติเอกสารทุกครั้ง"""
    from apps.documents.models import DocumentEvent
    from apps.documents.services import log_event

    document = _letter_or_404(request, pk)
    name, data = services.docx_for(document)
    log_event(document, request.user, DocumentEvent.Action.DOWNLOADED, client_ip(request), file=name)
    return FileResponse(
        BytesIO(data), as_attachment=True, filename=name,
        content_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
    )


@capability_required("manage_registers")
def letterhead(request):
    head = Letterhead.current()
    form = LetterheadForm(request.POST or None, request.FILES or None, instance=head)
    if request.method == "POST":
        if form.is_valid():
            upload = form.cleaned_data.get("emblem")
            try:
                head = form.save(commit=False)
                head.updated_by = request.user
                if upload:
                    services.save_emblem(head, upload.read(), request.user)
                else:
                    head.save()
            except ValidationError as exc:
                form.add_error("emblem", " ".join(exc.messages))
            else:
                from apps.audit import services as audit

                audit.record("SETTINGS", "LETTERHEAD_SAVED", "บันทึกหัวหนังสือ", actor=request.user,
                             ip=client_ip(request), emblem_changed=bool(upload))
                messages.success(request, "บันทึกหัวหนังสือแล้ว ใช้กับหนังสือที่สร้างหรือแก้ไขหลังจากนี้")
                return redirect("letters:letterhead")
        messages.error(request, "ยังไม่ได้บันทึก กรุณาตรวจข้อมูล")
    return render(request, "letters/letterhead.html", {"form": form, "head": head})


@capability_required("manage_registers")
def emblem_image(request):
    from django.http import HttpResponse

    data = services.emblem_png(Letterhead.current())
    if not data:
        raise Http404
    response = HttpResponse(data, content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response
