"""
การแจ้งเตือนในระบบ เช่น มีเรื่องรอพิจารณา ถูกส่งกลับแก้ไข ได้รับมอบหมายงาน เรื่องเสร็จสิ้น ออกเลขแล้ว ลงนามแล้ว
แจ้งเฉพาะผู้ที่มีสิทธิ์เห็นเอกสารนั้น (ตรวจตอนสร้างและตอนเปิดอ่าน)
"""
from django.conf import settings
from django.db import models
from django.utils import timezone


class Notification(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="notifications")
    title = models.CharField(max_length=200)
    body = models.CharField(max_length=500, blank=True)
    url = models.CharField(max_length=300, blank=True)
    document = models.ForeignKey(
        "documents.Document", null=True, blank=True, on_delete=models.CASCADE, related_name="notifications"
    )
    created_at = models.DateTimeField(default=timezone.now)
    read_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]
        indexes = [models.Index(fields=["user", "read_at"], name="notificatio_user_id_9c4a7b_idx")]

    def __str__(self):
        return self.title

    @property
    def is_read(self):
        return self.read_at is not None
