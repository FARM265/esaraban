"""
หนังสือที่สร้างจากแม่แบบ (หนังสือภายนอก บันทึกข้อความ คำสั่ง ประกาศ)

- Letterhead     ข้อมูลหัวหนังสือของสำนักงาน (ชื่อ ที่อยู่ ภาพตราครุฑ) มีแถวเดียว ผู้ดูแลระบบแก้ไขได้
- LetterContent  เนื้อหาที่ผู้ใช้กรอก ระบบสร้าง PDF จากข้อมูลนี้ และจำตำแหน่งที่ต้องประทับเลขที่/วันที่ตอนออกเลข

เอกสารเป็นร่าง (ยังไม่มีเลข) จนกว่าเจ้าหน้าที่สารบรรณจะออกเลข เมื่อออกเลขแล้วแก้เนื้อหาไม่ได้อีก
"""
from django.conf import settings
from django.db import models
from django.utils import timezone

from apps.documents.models import DocumentKind

LETTER_KINDS = [
    (DocumentKind.OUTGOING, "หนังสือภายนอก (หนังสือส่ง)"),
    (DocumentKind.INTERNAL, "บันทึกข้อความ"),
    (DocumentKind.ORDER, "คำสั่ง"),
    (DocumentKind.ANNOUNCE, "ประกาศ"),
]
REGISTER_TYPE_FOR = {
    DocumentKind.OUTGOING: "SEND",
    DocumentKind.INTERNAL: "INTERNAL",
    DocumentKind.ORDER: "ORDER",
    DocumentKind.ANNOUNCE: "ANNOUNCE",
}


class Letterhead(models.Model):
    org_name = models.CharField("ชื่อส่วนราชการ", max_length=200)
    address = models.TextField("ที่ตั้ง", blank=True, help_text="บรรทัดละ 1 ส่วน เช่น เลขที่และถนน / อำเภอ จังหวัด รหัสไปรษณีย์")
    default_contact = models.TextField(
        "ส่วนราชการเจ้าของเรื่อง (ค่าเริ่มต้น)", blank=True,
        help_text="แสดงมุมล่างซ้ายของหนังสือภายนอก เช่น กลุ่มงาน... / โทร. ... ผู้สร้างหนังสือแก้ไขได้ทุกฉบับ",
    )
    emblem_key = models.CharField(max_length=255, blank=True, editable=False)
    emblem_sha256 = models.CharField(max_length=64, blank=True, editable=False)
    updated_by = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.PROTECT, related_name="+")
    updated_at = models.DateTimeField(default=timezone.now)

    class Meta:
        verbose_name = "หัวหนังสือ"
        verbose_name_plural = "หัวหนังสือ"

    def __str__(self):
        return self.org_name

    @classmethod
    def current(cls):
        obj, _ = cls.objects.get_or_create(pk=1, defaults={"org_name": settings.ESARABAN_ORG_NAME})
        return obj

    @property
    def address_lines(self):
        return [line.strip() for line in self.address.splitlines() if line.strip()]


class LetterContent(models.Model):
    document = models.OneToOneField(
        "documents.Document", primary_key=True, on_delete=models.PROTECT, related_name="letter"
    )
    reference = models.CharField("อ้างถึง", max_length=500, blank=True)
    enclosures = models.TextField("สิ่งที่ส่งมาด้วย", blank=True, help_text="บรรทัดละ 1 รายการ")
    body = models.TextField("ข้อความ", help_text="ขึ้นบรรทัดใหม่ = ขึ้นย่อหน้าใหม่ ระบบตัดคำและย่อหน้าให้อัตโนมัติ")
    closing = models.CharField("คำลงท้าย", max_length=100, blank=True, default="ขอแสดงความนับถือ")
    signer_name = models.CharField("ชื่อผู้ลงนาม", max_length=200, blank=True, help_text="ไม่ต้องใส่วงเล็บ")
    signer_position = models.TextField("ตำแหน่งผู้ลงนาม", blank=True, help_text="บรรทัดละ 1 บรรทัด")
    department_line = models.CharField(
        "ส่วนราชการ", max_length=300, blank=True, help_text="บันทึกข้อความ: เช่น กลุ่มงาน... โทร. ..."
    )
    contact = models.TextField("ส่วนราชการเจ้าของเรื่อง", blank=True, help_text="หนังสือภายนอก: บรรทัดละ 1 บรรทัด")
    number_anchor = models.JSONField(null=True, blank=True, editable=False)
    date_anchor = models.JSONField(null=True, blank=True, editable=False)
    sign_anchor = models.JSONField(null=True, blank=True, editable=False)
    letter_date = models.DateField("ลงวันที่", null=True, blank=True, editable=False)
    revision = models.PositiveIntegerField(default=1, editable=False)

    class Meta:
        verbose_name = "เนื้อหาหนังสือ"
        verbose_name_plural = "เนื้อหาหนังสือ"

    def __str__(self):
        return str(self.document)

    @staticmethod
    def lines(text):
        return [line.strip() for line in (text or "").splitlines() if line.strip()]

    @property
    def paragraphs(self):
        return self.lines(self.body)
