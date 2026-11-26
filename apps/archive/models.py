"""
การจัดเก็บเอกสารเข้าคลัง

เอกสารที่จัดเก็บแล้วมีสถานะ "จัดเก็บ" อ่านได้อย่างเดียว ArchiveRecord เก็บหมวด/แฟ้ม อายุการเก็บ และวันที่ครบกำหนด
นำออกจากคลังได้ (เช่น ต้องดำเนินการต่อ) โดยระบุเหตุผล ประวัติการจัดเก็บทุกครั้งยังอยู่ครบ
ระบบไม่ทำลายเอกสาร รายการ "ครบกำหนด" เป็นเพียงรายงานให้คณะกรรมการพิจารณาตามระเบียบงานสารบรรณ
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Retention(models.IntegerChoices):
    ONE = 1, "1 ปี"
    FIVE = 5, "5 ปี"
    TEN = 10, "10 ปี (ทั่วไป)"
    TWENTY = 20, "20 ปี"
    PERMANENT = 0, "เก็บตลอดไป"


class ArchiveRecord(models.Model):
    document = models.ForeignKey("documents.Document", on_delete=models.PROTECT, related_name="archive_records")
    folder = models.CharField("หมวด/แฟ้ม", max_length=200)
    retention_years = models.PositiveSmallIntegerField("อายุการเก็บ", choices=Retention.choices, default=Retention.TEN)
    keep_until = models.DateField("เก็บถึง", null=True, blank=True)
    note = models.TextField("หมายเหตุ", blank=True)
    previous_status = models.CharField(max_length=20)
    archived_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    archived_at = models.DateTimeField(default=timezone.now)
    released_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    released_at = models.DateTimeField(null=True, blank=True)
    release_reason = models.TextField(blank=True)

    class Meta:
        ordering = ["-archived_at"]
        constraints = [
            models.UniqueConstraint(
                fields=["document"], condition=models.Q(released_at__isnull=True), name="one_active_archive_record"
            ),
        ]

    def __str__(self):
        return f"{self.document} ({self.folder})"


class ArchiveFolder(models.Model):
    """หมวด/แฟ้มที่ใช้จัดเก็บ ให้เลือกจากรายการเดียวกัน (สร้างใหม่ได้ตอนจัดเก็บ) ชื่อจึงไม่สะกดต่างกันจนแยกแฟ้ม"""

    name = models.CharField("ชื่อหมวด/แฟ้ม", max_length=200, unique=True)
    created_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.SET_NULL, related_name="+"
    )
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ["name"]
        verbose_name = "หมวด/แฟ้ม"
        verbose_name_plural = "หมวด/แฟ้ม"

    def __str__(self):
        return self.name
