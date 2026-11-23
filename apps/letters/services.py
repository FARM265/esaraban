"""
สร้าง แก้ไข และออกเลขหนังสือจากแม่แบบ

- create_letter   สร้างเอกสารสถานะ "ร่าง" พร้อมไฟล์ PDF จากแม่แบบ (ยังไม่มีเลข)
- revise_letter   แก้ไขร่าง ได้ไฟล์ร่างฉบับใหม่ (ฉบับเก่ายังเก็บไว้)
- issue_number    ออกเลขจากทะเบียนส่ง/บันทึกข้อความ/คำสั่ง/ประกาศ แล้วประทับเลขที่และวันที่ลงบนไฟล์หลักล่าสุด
                  (รวมไฟล์ที่ลงนามหรือเกษียนแล้ว) ทั้งหมดอยู่ใน transaction เดียว ถ้าล้มเหลวเลขจะไม่ถูกใช้
"""
import re
from io import BytesIO

from django.conf import settings
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Max
from django.utils import timezone
from PIL import Image, UnidentifiedImageError

from apps.accounts.permissions import has_capability
from apps.core.constants import SecrecyLevel, Urgency
from apps.core.templatetags.thai_date import thai_date
from apps.documents import access, storage
from apps.documents.models import Attachment, Document, DocumentEvent, DocumentStatus
from apps.documents.services import log_event
from apps.registry.models import RegisterBook
from apps.registry.services import issue_number as registry_issue_number
from apps.signatures import pdfsign, stamping

from . import layout
from .models import REGISTER_TYPE_FOR, LetterContent, Letterhead

EDITABLE_STATUSES = {DocumentStatus.DRAFT, DocumentStatus.RETURNED}
NOT_ISSUABLE_STATUSES = {DocumentStatus.IN_REVIEW, DocumentStatus.RETURNED, DocumentStatus.CANCELLED,
                         DocumentStatus.ARCHIVED}
MAX_EMBLEM_BYTES = 2 * 1024 * 1024


def _safe_name(text):
    return re.sub(r'[\\/:*?"<>|]+', "-", text).strip()[:150]


def fonts():
    regular = settings.ESARABAN_TEXT_FONT
    bold = settings.ESARABAN_TEXT_FONT_BOLD
    if not regular.exists():
        raise ValidationError("ไม่พบฟอนต์ Sarabun สำหรับสร้างหนังสือ กรุณาให้ผู้ดูแลระบบ build ระบบใหม่")
    return regular, (bold if bold.exists() else regular)


# ---------------------------------------------------------------- สิทธิ์
def is_letter(document):
    return LetterContent.objects.filter(pk=document.pk).exists()


def can_create(user):
    return has_capability(user, "create_documents")


def can_revise(user, document):
    return (
        document.registration_id is None
        and document.status in EDITABLE_STATUSES
        and is_letter(document)
        and access.can_view(user, document)
        and (document.created_by_id == user.pk or has_capability(user, "create_documents", document.owner_department))
    )


def can_issue(user, document):
    return (
        document.registration_id is None
        and document.status not in NOT_ISSUABLE_STATUSES
        and is_letter(document)
        and access.can_view(user, document)
        and has_capability(user, "register_documents", document.owner_department)
    )


def books_for(document):
    return RegisterBook.objects.filter(register_type=REGISTER_TYPE_FOR[document.kind], is_active=True)


# ---------------------------------------------------------------- สร้างไฟล์
def emblem_png(letterhead):
    if not letterhead.emblem_key:
        return None
    return storage.read_decrypted(letterhead.emblem_key, letterhead.emblem_sha256)


def build_spec(document, letter, letterhead=None):
    head = letterhead or Letterhead.current()
    return layout.LetterSpec(
        kind=document.kind,
        org_name=head.org_name,
        org_address=head.address_lines,
        emblem_png=emblem_png(head),
        subject=document.subject,
        recipient=document.recipient,
        reference=letter.reference,
        enclosures=letter.lines(letter.enclosures),
        body=letter.paragraphs,
        closing=letter.closing,
        signer_name=letter.signer_name,
        signer_position=letter.lines(letter.signer_position),
        department_line=letter.department_line,
        contact=letter.lines(letter.contact),
        urgency=Urgency(document.urgency).label if document.urgency else "",
        secrecy=SecrecyLevel(document.secrecy).label if document.secrecy else "",
    )


def render_letter(document, letter):
    regular, bold = fonts()
    return layout.build(build_spec(document, letter), regular, bold)


def _store_version(document, user, pdf, pages, name, *, signed=False):
    """บันทึกไฟล์หลักเวอร์ชันใหม่ ต้องเรียกภายใน transaction ที่ล็อกเอกสารแล้ว"""
    key, digest = storage.save_encrypted(pdf)
    try:
        version = (document.attachments.aggregate(v=Max("version"))["v"] or 0) + 1
        return Attachment.objects.create(
            document=document, original_name=f"{_safe_name(name)}.pdf", storage_key=key, size=len(pdf),
            sha256=digest, page_count=pages, is_main=True, is_signed_copy=signed, version=version,
            uploaded_by=user,
        ), key
    except Exception:
        storage.remove_quietly(key)
        raise


def _apply_render(letter, result):
    letter.number_anchor = result.number_anchor
    letter.date_anchor = result.date_anchor
    letter.sign_anchor = result.sign_anchor


def create_letter(*, kind, document_data, content_data, user, ip=None):
    if not can_create(user):
        raise PermissionDenied
    keys = []
    try:
        with transaction.atomic():
            document = Document.objects.create(
                kind=kind, status=DocumentStatus.DRAFT, created_by=user, **document_data
            )
            letter = LetterContent(document=document, **content_data)
            result = render_letter(document, letter)
            _apply_render(letter, result)
            letter.save()
            attachment, key = _store_version(
                document, user, result.pdf, result.pages, f"ร่าง{document.get_kind_display()} - {document.subject}"
            )
            keys.append(key)
            log_event(document, user, DocumentEvent.Action.DRAFTED, ip, file=attachment.original_name)
    except Exception:
        for key in keys:
            storage.remove_quietly(key)
        raise
    return document


def revise_letter(*, document, document_data, content_data, user, ip=None):
    keys = []
    try:
        with transaction.atomic():
            document = Document.objects.select_for_update().get(pk=document.pk)
            if not can_revise(user, document):
                raise PermissionDenied
            for field, value in document_data.items():
                setattr(document, field, value)
            document.save()
            letter = document.letter
            for field, value in content_data.items():
                setattr(letter, field, value)
            letter.revision += 1
            result = render_letter(document, letter)
            _apply_render(letter, result)
            letter.save()
            attachment, key = _store_version(
                document, user, result.pdf, result.pages,
                f"ร่าง{document.get_kind_display()} - {document.subject} (แก้ไขครั้งที่ {letter.revision - 1})",
            )
            keys.append(key)
            log_event(document, user, DocumentEvent.Action.DRAFT_REVISED, ip, file=attachment.original_name)
    except Exception:
        for key in keys:
            storage.remove_quietly(key)
        raise
    return document


# ---------------------------------------------------------------- ออกเลข
def issue_number(*, document, book, user, ip=None, today=None):
    keys = []
    try:
        with transaction.atomic():
            document = Document.objects.select_for_update().get(pk=document.pk)
            if not can_issue(user, document):
                raise PermissionDenied
            if book.register_type != REGISTER_TYPE_FOR[document.kind] or not book.is_active:
                raise ValidationError("ชุดทะเบียนนี้ใช้กับหนังสือประเภทนี้ไม่ได้")
            letter = document.letter
            source_file = document.main_attachment
            if source_file is None:
                raise ValidationError("ไม่พบไฟล์หลักของหนังสือ")
            source = storage.read_decrypted(source_file.storage_key, source_file.sha256)
            if pdfsign.has_signatures(source):
                raise ValidationError(
                    "ไฟล์ล่าสุดมีลายมือชื่อดิจิทัลแล้ว ประทับเลขที่ลงไปจะทำให้ลายมือชื่อใช้ไม่ได้ "
                    "ต้องออกเลขก่อนลงนามดิจิทัล (ถ้าลงนามไปแล้ว ให้สร้างร่างใหม่ หรือออกเลขจากเมนูทะเบียนเลขหนังสือแทน)"
                )
            number = registry_issue_number(book, user, subject=document.subject, recipient=document.recipient)
            day = today or timezone.localdate()
            regular, _ = fonts()
            ts = layout.Typesetter(regular)
            stamps = []
            for anchor, text in ((letter.number_anchor, number.display_no), (letter.date_anchor, thai_date(day, "full"))):
                if anchor:
                    width, height = stamping.page_size(source, anchor["page"])
                    stamps.append(layout.anchor_stamp(ts, anchor, text, width, height))
            try:
                result = stamping.stamp_images(source, stamps) if stamps else source
            except stamping.StampError as exc:
                raise ValidationError(str(exc)) from exc
            attachment, key = _store_version(
                document, user, result, source_file.page_count,
                f"{document.get_kind_display()} {number.display_no} - {document.subject}",
                signed=source_file.is_signed_copy,
            )
            keys.append(key)
            letter.letter_date = day
            letter.save(update_fields=["letter_date"])
            document.registration = number
            if document.status == DocumentStatus.DRAFT:
                document.status = DocumentStatus.REGISTERED
            document.save(update_fields=["registration", "status", "updated_at"])
            log_event(document, user, DocumentEvent.Action.NUMBER_ISSUED, ip,
                      number=number.display_no, file=attachment.original_name)
            from apps.notifications.services import notify

            notify([document.created_by], f"ออกเลข {number.display_no} แล้ว", body=document.subject,
                   document=document, exclude=user)
    except Exception:
        for key in keys:
            storage.remove_quietly(key)
        raise
    return number


# ---------------------------------------------------------------- ไฟล์ Word
def docx_for(document):
    """ไฟล์ Word ของหนังสือ (ถ้าออกเลขแล้วใส่เลขที่และวันที่ให้) คืนค่า (ชื่อไฟล์, bytes)"""
    from . import wordexport

    letter = document.letter
    number = document.registration.display_no if document.registration_id else ""
    date_text = thai_date(letter.letter_date, "full") if letter.letter_date else ""
    data = wordexport.build_docx(build_spec(document, letter), number_text=number, date_text=date_text)
    name = f"{document.get_kind_display()} {number or 'ร่าง'} - {document.subject}"
    return f"{_safe_name(name)}.docx", data


# ---------------------------------------------------------------- หัวหนังสือ
def save_emblem(letterhead, data, user):
    """ภาพตราครุฑ: PNG/JPG แปลงเป็น PNG พื้นโปร่งใส (ลบพื้นขาว) ย่อไม่เกิน 1200 px"""
    if len(data) > MAX_EMBLEM_BYTES:
        raise ValidationError("ภาพใหญ่เกิน 2 MB")
    try:
        image = Image.open(BytesIO(data))
        if image.format not in ("PNG", "JPEG"):
            raise ValidationError("รับเฉพาะไฟล์ PNG หรือ JPG")
        image.load()
    except (UnidentifiedImageError, OSError) as exc:
        raise ValidationError("ไฟล์ภาพเสียหายหรือไม่ใช่ภาพ") from exc
    image = image.convert("RGBA")
    image.thumbnail((1200, 1200))
    pixels = [(r, g, b, 0) if r > 235 and g > 235 and b > 235 else (r, g, b, a) for r, g, b, a in image.getdata()]
    image.putdata(pixels)
    box = image.getbbox()
    if not box:
        raise ValidationError("ภาพว่างเปล่า")
    out = BytesIO()
    image.crop(box).save(out, format="PNG", optimize=True)
    old = letterhead.emblem_key
    letterhead.emblem_key, letterhead.emblem_sha256 = storage.save_encrypted(out.getvalue())
    letterhead.updated_by = user
    letterhead.updated_at = timezone.now()
    letterhead.save()
    if old:
        storage.remove_quietly(old)
    return letterhead
