"""
API ความเห็นและข้อความสั่งการ/เกษียนบน PDF (ใช้โดย static/js/pdf-viewer.js)

ตรวจสิทธิ์ทุกคำขอ: ต้องเห็นเอกสารนั้นได้ (apps.documents.access) และใช้ CSRF ตามปกติของ Django
ข้อความสั่งการ/เกษียน (TEXT) เขียนได้เฉพาะผู้มีสิทธิ์ endorse_documents
เนื้อหาถูกแสดงด้วย textContent ฝั่งเบราว์เซอร์ จึงไม่รันเป็น HTML
"""
import json

from django.core.exceptions import PermissionDenied
from django.http import Http404, HttpResponseNotAllowed, JsonResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.documents import access
from apps.documents.models import LOCKED_STATUSES, Attachment

from . import render, services
from .models import INK_COLORS, INK_SIZES, Annotation

MAX_LEN = 2000


def _attachment_or_404(request, attachment_id):
    attachment = get_object_or_404(Attachment.objects.select_related("document"), pk=attachment_id)
    if not access.can_view(request.user, attachment.document):
        raise Http404
    return attachment


def _error(message, status=400):
    return JsonResponse({"error": message}, status=status)


def annotation_list(request, attachment_id):
    attachment = _attachment_or_404(request, attachment_id)
    if request.method == "GET":
        items = attachment.annotations.filter(deleted_at__isnull=True).select_related("author")
        return JsonResponse({"annotations": [a.as_dict(request.user) for a in items]})
    if request.method != "POST":
        return HttpResponseNotAllowed(["GET", "POST"])
    if attachment.document.status in LOCKED_STATUSES:
        return _error("เอกสารนี้ถูกยกเลิกแล้ว")
    try:
        payload = json.loads(request.body or b"{}")
        kind = str(payload.get("kind", Annotation.Kind.NOTE))
        page = int(payload.get("page"))
        x = float(payload.get("x"))
        y = float(payload.get("y"))
        content = str(payload.get("content", "")).strip("\n ").rstrip()
        color = str(payload.get("color", "blue"))
        size = str(payload.get("size", "M"))
    except (TypeError, ValueError):
        return _error("ข้อมูลไม่ถูกต้อง")
    if kind not in Annotation.Kind.values:
        return _error("ชนิดไม่ถูกต้อง")
    if kind == Annotation.Kind.TEXT and not services.can_endorse(request.user, attachment.document):
        return _error("ท่านไม่มีสิทธิ์สั่งการ/เกษียน", 403)
    max_page = attachment.page_count or 10_000
    if not (1 <= page <= max_page and 0 <= x <= 1 and 0 <= y <= 1):
        return _error("ตำแหน่งไม่ถูกต้อง")
    if not content.strip():
        return _error("กรุณาพิมพ์ข้อความ")
    if len(content) > MAX_LEN:
        return _error(f"ข้อความยาวเกิน {MAX_LEN} ตัวอักษร")
    if kind == Annotation.Kind.TEXT and len(content.splitlines()) > render.MAX_LINES:
        return _error(f"ข้อความยาวเกิน {render.MAX_LINES} บรรทัด")
    if color not in INK_COLORS or size not in INK_SIZES:
        return _error("สีหรือขนาดไม่ถูกต้อง")
    annotation = Annotation.objects.create(
        attachment=attachment, kind=kind, page=page, x=x, y=y, content=content,
        color=color, size=size, author=request.user,
    )
    return JsonResponse({"annotation": annotation.as_dict(request.user)}, status=201)


def _own_annotation(request, pk):
    annotation = get_object_or_404(
        Annotation.objects.select_related("attachment__document"), pk=pk, deleted_at__isnull=True
    )
    if not access.can_view(request.user, annotation.attachment.document):
        raise Http404
    if annotation.author_id != request.user.pk:
        raise PermissionDenied
    return annotation


@require_POST
def annotation_delete(request, pk):
    try:
        annotation = _own_annotation(request, pk)
    except PermissionDenied:
        return _error("ลบได้เฉพาะของตนเอง", 403)
    annotation.deleted_at = timezone.now()
    annotation.deleted_by = request.user
    annotation.save(update_fields=["deleted_at", "deleted_by"])
    return JsonResponse({"ok": True})


@require_POST
def annotation_move(request, pk):
    try:
        annotation = _own_annotation(request, pk)
    except PermissionDenied:
        return _error("ย้ายได้เฉพาะของตนเอง", 403)
    try:
        payload = json.loads(request.body or b"{}")
        x, y = float(payload.get("x")), float(payload.get("y"))
    except (TypeError, ValueError):
        return _error("ข้อมูลไม่ถูกต้อง")
    if not (0 <= x <= 1 and 0 <= y <= 1):
        return _error("ตำแหน่งไม่ถูกต้อง")
    annotation.x, annotation.y = x, y
    annotation.save(update_fields=["x", "y"])
    return JsonResponse({"annotation": annotation.as_dict(request.user)})
