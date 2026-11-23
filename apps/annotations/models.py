"""
สิ่งที่ผู้ใช้เขียนลงบนหน้า PDF มี 2 แบบ

- NOTE (หมุดความเห็น)  คุยกันภายในระบบ ไม่ลงในเนื้อเอกสาร
- TEXT (ข้อความสั่งการ/เกษียน) พิมพ์ลงบนหน้าเอกสาร เลือกสีหมึกและขนาดได้
  เมื่อกด "สร้างไฟล์ฉบับใหม่" ระบบฝังข้อความลงใน PDF เป็นไฟล์ฉบับใหม่

ตำแหน่งเก็บเป็นสัดส่วน 0–1 ของหน้า (TEXT = มุมซ้ายบนของข้อความ, NOTE = ปลายหมุด)
ขนาดตัวอักษรเก็บเป็นสัดส่วนของความกว้างหน้า จึงแสดงถูกต้องทุกระดับซูม
ลบได้เฉพาะผู้เขียน และเป็นการลบแบบเก็บร่องรอย (deleted_at) ไม่ลบจริง
"""
from django.conf import settings
from django.core.validators import MaxValueValidator, MinValueValidator
from django.db import models
from django.utils import timezone

A4_WIDTH_PT = 595

INK_COLORS = {
    "blue": ("น้ำเงิน", "#1F3A93"),
    "red": ("แดง", "#B42318"),
    "black": ("ดำ", "#111111"),
    "green": ("เขียว", "#1E7B34"),
}
# ขนาดเทียบกับหน้า A4 แนวตั้ง (pt) เก็บเป็นสัดส่วนความกว้างหน้า
INK_SIZES = {
    "S": ("เล็ก", 12),
    "M": ("กลาง", 16),
    "L": ("ใหญ่", 22),
}


class Annotation(models.Model):
    class Kind(models.TextChoices):
        NOTE = "NOTE", "หมุดความเห็น"
        TEXT = "TEXT", "ข้อความสั่งการ/เกษียน"

    attachment = models.ForeignKey("documents.Attachment", on_delete=models.PROTECT, related_name="annotations")
    kind = models.CharField(max_length=10, choices=Kind.choices, default=Kind.NOTE)
    page = models.PositiveIntegerField(validators=[MinValueValidator(1)])
    x = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(1)])
    y = models.FloatField(validators=[MinValueValidator(0), MaxValueValidator(1)])
    content = models.TextField(max_length=2000)
    color = models.CharField(max_length=10, choices=[(k, v[0]) for k, v in INK_COLORS.items()], default="blue")
    size = models.CharField(max_length=2, choices=[(k, v[0]) for k, v in INK_SIZES.items()], default="M")
    author = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="annotations")
    created_at = models.DateTimeField(default=timezone.now)
    deleted_at = models.DateTimeField(null=True, blank=True)
    deleted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    class Meta:
        ordering = ["page", "created_at"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(x__gte=0, x__lte=1, y__gte=0, y__lte=1), name="annotation_position_in_page"
            ),
        ]

    def __str__(self):
        return f"หน้า {self.page}: {self.content[:30]}"

    @property
    def color_hex(self):
        return INK_COLORS[self.color][1]

    @property
    def size_ratio(self):
        """ขนาดตัวอักษรเทียบความกว้างหน้า"""
        return INK_SIZES[self.size][1] / A4_WIDTH_PT

    def as_dict(self, viewer):
        from apps.core.templatetags.thai_date import thai_datetime

        return {
            "id": self.pk,
            "kind": self.kind,
            "page": self.page,
            "x": self.x,
            "y": self.y,
            "content": self.content,
            "color": self.color_hex,
            "size_ratio": self.size_ratio,
            "author": self.author.display_name_th,
            "created_at": thai_datetime(self.created_at),
            "can_delete": self.author_id == viewer.pk,
        }
