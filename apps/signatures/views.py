from django.conf import settings
from django.contrib import messages
from django.core.exceptions import PermissionDenied, ValidationError
from django.http import Http404, HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.views.decorators.cache import never_cache
from django.views.decorators.http import require_POST

from apps.accounts.permissions import capability_required
from apps.accounts.security import client_ip
from apps.documents import access
from apps.documents.models import Attachment

from . import digital, services
from .models import TestCertificateAuthority
from .forms import FinalCopyForm, SignatureUploadForm


@capability_required("sign_documents")
def my_signature(request):
    form = SignatureUploadForm(request.POST or None, request.FILES or None)
    if request.method == "POST":
        if form.is_valid():
            try:
                services.upload_signature_image(request.user, form.cleaned_data["image"].read())
                messages.success(request, "บันทึกภาพลายมือชื่อแล้ว")
                return redirect("signatures:my_signature")
            except ValidationError as exc:
                form.add_error("image", " ".join(exc.messages))
        messages.error(request, "ยังไม่ได้บันทึก กรุณาตรวจไฟล์ภาพ")
    return render(
        request,
        "signatures/my_signature.html",
        {
            "form": form,
            "current": services.active_signature_image(request.user),
            "sign_require_otp": settings.ESARABAN_SIGN_REQUIRE_OTP,
            "credential": digital.active_credential(request.user),
            "has_ca": TestCertificateAuthority.objects.exists(),
            "digital_enabled": digital.enabled(),
        },
    )


def test_ca(request):
    """ใบรับรอง CA ทดสอบ (ข้อมูลสาธารณะ ไม่มีกุญแจลับ) ให้ผู้ทดสอบนำไปตั้งค่าโปรแกรมอ่าน PDF ให้เชื่อถือ"""
    authority = TestCertificateAuthority.objects.order_by("pk").first()
    if authority is None:
        raise Http404
    response = HttpResponse(authority.cert_pem, content_type="application/x-x509-ca-cert")
    response["Content-Disposition"] = 'attachment; filename="esaraban-test-ca.crt"'
    return response


@never_cache
def my_signature_image(request):
    """ภาพลายมือชื่อของผู้ใช้เอง (ไม่มีทางเปิดภาพของคนอื่นผ่าน URL นี้)"""
    image = services.active_signature_image(request.user)
    if image is None:
        raise Http404
    response = HttpResponse(services.read_signature_png(image), content_type="image/png")
    response["Cache-Control"] = "private, no-store"
    return response


@require_POST
def final_copy(request, attachment_id):
    """ปุ่มเดียวในตัวดู PDF: ฝังข้อความสั่งการ/เกษียน และ/หรือ ลายเซ็น ลงไฟล์ฉบับใหม่ไฟล์เดียว"""
    attachment = get_object_or_404(Attachment.objects.select_related("document"), pk=attachment_id)
    if not access.can_view(request.user, attachment.document):
        raise Http404
    back = redirect("documents:viewer", pk=attachment.pk)
    form = FinalCopyForm(request.POST, attachment=attachment)
    if not form.is_valid():
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"ยังไม่ได้สร้างไฟล์: {errors}")
        return back
    signature = form.cleaned_data["signature"]
    try:
        new_file = services.create_final_copy(
            attachment=attachment, user=request.user, signature=signature,
            otp_code=form.cleaned_data["code"], ip=client_ip(request),
        )
    except PermissionDenied:
        messages.error(request, "ท่านไม่มีสิทธิ์สั่งการ/เกษียนหรือลงนามเอกสารนี้")
        return back
    except ValidationError as exc:
        messages.error(request, " ".join(exc.messages))
        return back
    messages.success(request, f"สร้างไฟล์ \"{new_file.original_name}\" แล้ว กำลังแสดงไฟล์ใหม่ ไฟล์เดิมยังเก็บไว้ครบ")
    return redirect("documents:viewer", pk=new_file.pk)
