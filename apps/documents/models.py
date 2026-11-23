"""
เอกสาร ไฟล์แนบ และประวัติการดำเนินการ

หนังสือรับลงทะเบียนที่ apps.documents ส่วนหนังสือส่ง/บันทึกข้อความ/คำสั่ง/ประกาศ สร้างจากแม่แบบที่ apps.letters
ไฟล์ทุกไฟล์เข้ารหัสก่อนเก็บ (apps.documents.storage) ตารางเก็บแค่ชื่อไฟล์ในที่เก็บและ hash
"""
import uuid

from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.core.constants import SecrecyLevel, Urgency


class DocumentKind(models.TextChoices):
    INCOMING = "INCOMING", "หนังสือรับ"
    OUTGOING = "OUTGOING", "หนังสือส่ง"
    INTERNAL = "INTERNAL", "บันทึกข้อความ"
    ORDER = "ORDER", "คำสั่ง"
    ANNOUNCE = "ANNOUNCE", "ประกาศ"
    OTHER = "OTHER", "อื่น ๆ"


class DocumentStatus(models.TextChoices):
    DRAFT = "DRAFT", "ร่าง"
    REGISTERED = "REGISTERED", "ลงทะเบียนแล้ว"
    IN_REVIEW = "IN_REVIEW", "อยู่ระหว่างเสนอ"
    RETURNED = "RETURNED", "ส่งกลับแก้ไข"
    PENDING_SIGNATURE = "PENDING_SIGNATURE", "รอลงนาม"
    COMMANDED = "COMMANDED", "สั่งการแล้ว"
    IN_PROGRESS = "IN_PROGRESS", "ดำเนินการ"
    DONE = "DONE", "เสร็จสิ้น"
    ARCHIVED = "ARCHIVED", "จัดเก็บ"
    CANCELLED = "CANCELLED", "ยกเลิก"


# เอกสารที่ยกเลิกหรือจัดเก็บเข้าคลังแล้ว อ่านได้อย่างเดียว (ห้ามเพิ่มความเห็น สั่งการ/เกษียน ลงนาม แก้ไข หรือเสนอ)
LOCKED_STATUSES = frozenset({DocumentStatus.CANCELLED, DocumentStatus.ARCHIVED})


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField("ประเภท", max_length=20, choices=DocumentKind.choices)
    subject = models.CharField("เรื่อง", max_length=500)
    source_doc_no = models.CharField("เลขที่หนังสือต้นทาง", max_length=100, blank=True)
    source_doc_date = models.DateField("ลงวันที่", null=True, blank=True)
    source_org = models.CharField("หน่วยงานต้นทาง", max_length=300, blank=True)
    recipient = models.CharField("เรียน", max_length=300, blank=True)
    urgency = models.PositiveSmallIntegerField("ความเร่งด่วน", choices=Urgency.choices, default=Urgency.NORMAL)
    secrecy = models.PositiveSmallIntegerField("ชั้นความลับ", choices=SecrecyLevel.choices, default=SecrecyLevel.NORMAL)
    status = models.CharField("สถานะ", max_length=20, choices=DocumentStatus.choices, default=DocumentStatus.REGISTERED)
    owner_department = models.ForeignKey(
        "accounts.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="documents",
        verbose_name="กลุ่มงานเจ้าของเรื่อง",
    )
    registration = models.OneToOneField(
        "registry.IssuedNumber",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="document",
        verbose_name="เลขทะเบียน",
    )
    due_date = models.DateField("กำหนดเสร็จ", null=True, blank=True)
    note = models.TextField("หมายเหตุ", blank=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="created_documents"
    )
    created_at = models.DateTimeField(default=timezone.now)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-created_at"]
        verbose_name = "เอกสาร"
        verbose_name_plural = "เอกสาร"
        indexes = [
            models.Index(fields=["status", "owner_department"], name="doc_status_dept"),
            models.Index(fields=["kind", "created_at"], name="doc_kind_created"),
            models.Index(fields=["due_date"], name="doc_due_date"),
        ]

    def __str__(self):
        return f"{self.registration or '-'} {self.subject}"

    @property
    def main_attachment(self):
        return self.attachments.filter(is_main=True).order_by("-version").first()


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="attachments")
    original_name = models.CharField("ชื่อไฟล์", max_length=255)
    storage_key = models.CharField(max_length=255, unique=True, editable=False)
    size = models.PositiveIntegerField("ขนาด (ไบต์)")
    sha256 = models.CharField(max_length=64, editable=False)
    content_type = models.CharField(max_length=100, default="application/pdf")
    page_count = models.PositiveIntegerField(null=True, blank=True)
    is_main = models.BooleanField("ไฟล์หลัก", default=False)
    is_signed_copy = models.BooleanField("ฉบับลงนาม", default=False)
    version = models.PositiveIntegerField(default=1)
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    uploaded_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-is_main", "uploaded_at"]
        verbose_name = "ไฟล์แนบ"
        verbose_name_plural = "ไฟล์แนบ"

    def __str__(self):
        return self.original_name


class DocumentEvent(models.Model):
    """ประวัติของเอกสารแต่ละฉบับ ใช้แสดงการติดตามสถานะ (ขั้นตอนที่ 8 จะส่งต่อเข้า Audit Log กลาง)"""

    class Action(models.TextChoices):
        REGISTERED = "REGISTERED", "ลงทะเบียน"
        UPDATED = "UPDATED", "แก้ไขข้อมูล"
        FILE_ADDED = "FILE_ADDED", "เพิ่มไฟล์"
        VIEWED = "VIEWED", "เปิดดูไฟล์"
        DOWNLOADED = "DOWNLOADED", "ดาวน์โหลดไฟล์"
        CANCELLED = "CANCELLED", "ยกเลิก"
        WORKFLOW_STARTED = "WF_STARTED", "เริ่มเสนอ"
        FORWARDED = "WF_FORWARD", "เสนอต่อ"
        RETURNED = "WF_RETURN", "ส่งกลับแก้ไข"
        RESUBMITTED = "WF_RESUBMIT", "เสนออีกครั้ง"
        COMMANDED = "WF_COMMAND", "สั่งการ"
        COMPLETED = "WF_COMPLETE", "ดำเนินการเสร็จ"
        WORKFLOW_CANCELLED = "WF_CANCEL", "ยกเลิกการเสนอ"
        SIGNED = "SIGNED", "ลงนาม"
        ENDORSED = "ENDORSED", "สั่งการ/เกษียน"
        DRAFTED = "DRAFTED", "สร้างร่างหนังสือ"
        DRAFT_REVISED = "DRAFT_REVISED", "แก้ไขร่างหนังสือ"
        NUMBER_ISSUED = "NUMBER_ISSUED", "ออกเลขหนังสือ"
        ARCHIVED = "ARCHIVED", "จัดเก็บเข้าคลัง"
        UNARCHIVED = "UNARCHIVED", "นำออกจากคลัง"

    document = models.ForeignKey(Document, on_delete=models.PROTECT, related_name="events")
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    action = models.CharField(max_length=20, choices=Action.choices)
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["document", "created_at"], name="docevent_doc_time")]

    def __str__(self):
        return f"{self.get_action_display()} {self.created_at:%Y-%m-%d %H:%M}"
