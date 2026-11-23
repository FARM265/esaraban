"""สิทธิ์และการเตรียมข้อความสั่งการ/เกษียน (การสร้างไฟล์ฉบับใหม่อยู่ที่ apps.signatures.services.create_final_copy)"""
from pathlib import Path

from django.conf import settings
from django.core.exceptions import ValidationError

from apps.accounts.permissions import has_capability
from apps.documents import access
from apps.documents.models import LOCKED_STATUSES, DocumentStatus
from apps.signatures import stamping

from . import render
from .models import Annotation


def can_endorse(user, document):
    return (
        document.status not in LOCKED_STATUSES
        and access.can_view(user, document)
        and has_capability(user, "endorse_documents", document.owner_department)
    )


def active_texts(attachment):
    return attachment.annotations.filter(kind=Annotation.Kind.TEXT, deleted_at__isnull=True).order_by("page", "created_at")


def text_stamps(texts, source_pdf):
    """แปลงข้อความสั่งการ/เกษียนเป็นภาพสำหรับ stamping.stamp_images (ขนาดตัวอักษรเทียบความกว้างหน้าเหมือนบนจอ)"""
    if not texts:
        return []
    font_path = Path(settings.ESARABAN_TEXT_FONT)
    if not font_path.exists():
        raise ValidationError("ไม่พบฟอนต์ Sarabun สำหรับเขียนลงไฟล์ กรุณาให้ผู้ดูแลระบบ build ระบบใหม่")
    widths = {}
    stamps = []
    for text in texts:
        if text.page not in widths:
            widths[text.page] = stamping.page_size(source_pdf, text.page)[0]
        width = widths[text.page]
        png, width_pt = render.render_text(
            text.content, color_hex=text.color_hex, font_pt=text.size_ratio * width, font_path=font_path
        )
        stamps.append({"page": text.page, "x": text.x, "y": text.y, "png": png, "width_ratio": min(width_pt / width, 1)})
    return stamps
