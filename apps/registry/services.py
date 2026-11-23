"""
ออกเลขและยกเลิกเลขหนังสือ

การออกเลขทำใน transaction เดียว ล็อกแถวตัวนับของชุดทะเบียน/ปีนั้นด้วย SELECT ... FOR UPDATE
คำขอที่เข้ามาพร้อมกันจึงต้องรอคิว และ unique constraint (book, year_be, running_no)
เป็นด่านสุดท้ายในระดับฐานข้อมูล ถ้ามีเลขซ้ำ transaction ทั้งชุดจะล้ม ไม่มีเลขข้ามหรือเลขซ้ำ
"""
from django.core.exceptions import ValidationError
from django.db import transaction
from django.utils import timezone

from .models import IssuedNumber, NumberSequence


def current_year_be():
    return timezone.localdate().year + 543


@transaction.atomic
def issue_number(book, user, subject="", recipient="", year_be=None):
    if not book.is_active:
        raise ValidationError("ชุดทะเบียนนี้ปิดใช้งานแล้ว")
    year_be = year_be or current_year_be()
    # get_or_create ปลอดภัยเมื่อแข่งกันสร้าง (ถ้าชน unique จะดึงแถวที่อีกฝั่งสร้าง)
    seq, _ = NumberSequence.objects.get_or_create(book=book, year_be=year_be)
    seq = NumberSequence.objects.select_for_update().get(pk=seq.pk)
    seq.last_number += 1
    seq.save(update_fields=["last_number"])
    issued = IssuedNumber.objects.create(
        book=book,
        year_be=year_be,
        running_no=seq.last_number,
        display_no=book.format_number(seq.last_number, year_be),
        subject=subject[:500],
        recipient=recipient[:300],
        issued_by=user,
    )
    from apps.audit import services as audit

    audit.record("REGISTRY", "NUMBER_ISSUED", f"ออกเลข {issued.display_no} ({book.name_th})", actor=user, target=issued)
    return issued


@transaction.atomic
def void_number(issued, user, reason):
    reason = (reason or "").strip()
    if not reason:
        raise ValidationError("ต้องระบุเหตุผลการยกเลิกเลข")
    issued = IssuedNumber.objects.select_for_update().get(pk=issued.pk)
    if issued.is_voided:
        raise ValidationError("เลขนี้ถูกยกเลิกไปแล้ว")
    issued.status = IssuedNumber.Status.VOIDED
    issued.voided_by = user
    issued.voided_at = timezone.now()
    issued.void_reason = reason
    issued.save(update_fields=["status", "voided_by", "voided_at", "void_reason"])
    from apps.audit import services as audit

    audit.record("REGISTRY", "NUMBER_VOIDED", f"ยกเลิกเลข {issued.display_no}", actor=user, target=issued,
                 reason=reason)
    return issued


def peek_next_number(book, year_be=None):
    """เลขถัดไปโดยประมาณ (ไม่จองเลข) สำหรับแสดงในหน้าจอเท่านั้น"""
    year_be = year_be or current_year_be()
    last = (
        NumberSequence.objects.filter(book=book, year_be=year_be).values_list("last_number", flat=True).first()
        or 0
    )
    return book.format_number(last + 1, year_be)
