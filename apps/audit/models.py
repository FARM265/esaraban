"""
Audit Log แบบเพิ่มได้อย่างเดียว (append-only)

- แต่ละรายการมีเลขลำดับ (seq) ต่อเนื่อง และ hash = SHA-256(ข้อมูลของรายการ + hash ของรายการก่อนหน้า)
  ถ้ามีการแก้ไข ลบ หรือแทรกรายการใดในภายหลัง การตรวจ chain จะพบตำแหน่งที่ผิดทันที
- แก้ไข/ลบผ่านโปรแกรมไม่ได้ (save/delete ยก exception) และบน PostgreSQL มี trigger ห้าม UPDATE/DELETE ที่ระดับฐานข้อมูล
- AuditChainHead เก็บลำดับและ hash ล่าสุด ใช้ล็อกให้การเขียนเรียงกันทีละรายการ และใช้ตรวจว่ารายการท้ายถูกลบหรือไม่
"""
from django.conf import settings
from django.db import models


class Category(models.TextChoices):
    AUTH = "AUTH", "เข้าสู่ระบบ"
    USER = "USER", "ผู้ใช้และสิทธิ์"
    DOCUMENT = "DOCUMENT", "เอกสาร"
    REGISTRY = "REGISTRY", "ทะเบียนเลข"
    SETTINGS = "SETTINGS", "ตั้งค่าระบบ"


class AuditEntry(models.Model):
    seq = models.BigIntegerField(unique=True, editable=False)
    at = models.DateTimeField(editable=False, db_index=True)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )
    actor_label = models.CharField(max_length=200, blank=True)
    category = models.CharField(max_length=20, choices=Category.choices, db_index=True)
    action = models.CharField(max_length=40, db_index=True)
    summary = models.CharField(max_length=500)
    target_type = models.CharField(max_length=40, blank=True)
    target_id = models.CharField(max_length=64, blank=True, db_index=True)
    detail = models.JSONField(default=dict, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    prev_hash = models.CharField(max_length=64, editable=False)
    hash = models.CharField(max_length=64, unique=True, editable=False)

    class Meta:
        ordering = ["-seq"]
        verbose_name = "รายการ Audit Log"
        verbose_name_plural = "Audit Log"

    def __str__(self):
        return f"#{self.seq} {self.action} {self.summary[:40]}"

    def save(self, *args, **kwargs):
        if self.pk is not None:
            raise PermissionError("Audit Log แก้ไขไม่ได้")
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise PermissionError("Audit Log ลบไม่ได้")


class AuditChainHead(models.Model):
    last_seq = models.BigIntegerField(default=0)
    last_hash = models.CharField(max_length=64, default="0" * 64)
