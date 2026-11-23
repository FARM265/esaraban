"""
บันทึกและตรวจ Audit Log

record(...)   เพิ่มรายการใหม่ ต่อ hash chain (ล็อก AuditChainHead จึงเขียนเรียงกันทีละรายการ)
              อยู่ใน transaction ของผู้เรียก ถ้างานหลักย้อนกลับ รายการ audit ก็ย้อนกลับด้วย ไม่มีบันทึกของสิ่งที่ไม่เกิดขึ้น
verify()      คำนวณ hash ใหม่ทุกรายการตามลำดับ แจ้งรายการแรกที่ผิด
"""
import datetime as dt
import hashlib
import json
from dataclasses import dataclass

from django.db import IntegrityError, transaction
from django.utils import timezone

from .models import AuditChainHead, AuditEntry, Category

GENESIS = "0" * 64


def _payload(entry):
    return {
        "seq": entry.seq,
        "at": entry.at.astimezone(dt.timezone.utc).isoformat(timespec="microseconds"),
        "actor": str(entry.actor_id or ""),
        "actor_label": entry.actor_label,
        "category": entry.category,
        "action": entry.action,
        "summary": entry.summary,
        "target_type": entry.target_type,
        "target_id": entry.target_id,
        "detail": entry.detail,
        "ip": entry.ip_address or "",
        "prev": entry.prev_hash,
    }


def compute_hash(entry):
    text = json.dumps(_payload(entry), ensure_ascii=False, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def _clean(value):
    """ทำให้ detail เป็น JSON ล้วน (ค่าจะถูกอ่านกลับมาเหมือนเดิมทุกครั้ง hash จึงคงที่)"""
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def _actor_label(actor, fallback=""):
    if actor is not None and getattr(actor, "is_authenticated", False):
        return f"{actor.display_name_th} ({actor.get_username()})"[:200]
    return (fallback or "")[:200]


def _locked_head():
    try:
        return AuditChainHead.objects.select_for_update().get(pk=1)
    except AuditChainHead.DoesNotExist:
        try:
            with transaction.atomic():
                AuditChainHead.objects.create(pk=1)
        except IntegrityError:  # อีกคำขอสร้างพร้อมกัน
            pass
        return AuditChainHead.objects.select_for_update().get(pk=1)


def record(category, action, summary, *, actor=None, actor_label="", target=None, ip=None, **detail):
    if category not in Category.values:
        raise ValueError("หมวด Audit Log ไม่ถูกต้อง")
    authenticated = actor is not None and getattr(actor, "is_authenticated", False)
    with transaction.atomic():
        head = _locked_head()
        entry = AuditEntry(
            seq=head.last_seq + 1,
            at=timezone.now(),
            actor=actor if authenticated else None,
            actor_label=_actor_label(actor, actor_label),
            category=category,
            action=str(action)[:40],
            summary=str(summary)[:500],
            target_type=target.__class__.__name__ if target is not None else "",
            target_id=str(target.pk) if target is not None else "",
            detail=_clean(detail),
            ip_address=ip or None,
            prev_hash=head.last_hash,
        )
        entry.hash = compute_hash(entry)
        entry.save()
        head.last_seq, head.last_hash = entry.seq, entry.hash
        head.save(update_fields=["last_seq", "last_hash"])
    return entry


def document_summary(document, label):
    """สรุปสำหรับ Audit Log ไม่เปิดเผยชื่อเรื่องของเอกสารชั้นความลับ (ผู้ตรวจสอบไม่มีสิทธิ์อ่านเนื้อหาเอกสาร)"""
    number = document.registration.display_no if document.registration_id else "ร่าง"
    subject = document.subject if not document.secrecy else f"[{document.get_secrecy_display()}]"
    return f"{label}: {number} {subject}"


@dataclass
class VerifyResult:
    ok: bool
    checked: int
    problem_seq: int = None
    problem: str = ""


def verify(batch=2000):
    previous_hash, expected_seq = GENESIS, 1
    checked = 0
    for entry in AuditEntry.objects.order_by("seq").iterator(chunk_size=batch):
        if entry.seq != expected_seq:
            return VerifyResult(False, checked, expected_seq, f"รายการลำดับที่ {expected_seq} หายไป")
        if entry.prev_hash != previous_hash:
            return VerifyResult(False, checked, entry.seq, "hash ของรายการก่อนหน้าไม่ตรงกัน")
        if compute_hash(entry) != entry.hash:
            return VerifyResult(False, checked, entry.seq, "ข้อมูลของรายการนี้ถูกแก้ไข")
        previous_hash, expected_seq = entry.hash, expected_seq + 1
        checked += 1
    head = AuditChainHead.objects.filter(pk=1).first()
    if head and (head.last_seq != checked or head.last_hash != previous_hash):
        return VerifyResult(False, checked, checked + 1, "รายการท้ายสุดหายไป หรือข้อมูลส่วนหัวไม่ตรงกัน")
    return VerifyResult(True, checked)
