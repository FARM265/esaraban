"""
ทะเบียนเลขหนังสือ

- RegisterBook   ชุดทะเบียน เช่น ทะเบียนรับกลาง ทะเบียนหนังสือส่ง กำหนดรูปแบบเลขได้
- NumberSequence ตัวนับล่าสุดของแต่ละชุดทะเบียนในแต่ละปี พ.ศ. (ล็อกด้วย select_for_update ตอนออกเลข)
- IssuedNumber   เลขที่ออกแล้วทุกเลข ห้ามลบ ยกเลิกได้โดยเก็บเหตุผลและผู้ยกเลิก

การออกเลขและยกเลิกเลขต้องทำผ่าน apps.registry.services เท่านั้น
"""
from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from .formatting import validate_number_format


class RegisterType(models.TextChoices):
    RECEIVE = "RECEIVE", "ทะเบียนรับ"
    SEND = "SEND", "ทะเบียนส่ง"
    INTERNAL = "INTERNAL", "หนังสือภายใน / บันทึกข้อความ"
    ORDER = "ORDER", "คำสั่ง"
    ANNOUNCE = "ANNOUNCE", "ประกาศ"


class RegisterBook(models.Model):
    code = models.CharField("รหัสชุดทะเบียน", max_length=20, unique=True)
    name_th = models.CharField("ชื่อชุดทะเบียน", max_length=200)
    register_type = models.CharField("ประเภท", max_length=20, choices=RegisterType.choices)
    org_code = models.CharField(
        "รหัสหน่วยงาน", max_length=50, blank=True, help_text="ใช้แทน {org} ในรูปแบบเลข เช่น ปช XXXX"
    )
    number_format = models.CharField(
        "รูปแบบเลข",
        max_length=100,
        validators=[validate_number_format],
        help_text="ใช้ได้: {org} รหัสหน่วยงาน, {no} เลขลำดับ (เช่น {no:04d} เติม 0 ให้ครบ 4 หลัก), {year} ปี พ.ศ.",
    )
    department = models.ForeignKey(
        "accounts.Department",
        null=True,
        blank=True,
        on_delete=models.PROTECT,
        related_name="register_books",
        verbose_name="กลุ่มงานเจ้าของ",
        help_text="เว้นว่าง = ใช้ร่วมทั้งสำนักงาน",
    )
    is_active = models.BooleanField("ใช้งานอยู่", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["register_type", "code"]
        verbose_name = "ชุดทะเบียน"
        verbose_name_plural = "ชุดทะเบียน"

    def __str__(self):
        return self.name_th

    def format_number(self, running_no, year_be):
        from .formatting import render_number

        return render_number(self.number_format, org=self.org_code, no=running_no, year=year_be)


class NumberSequence(models.Model):
    book = models.ForeignKey(RegisterBook, on_delete=models.PROTECT, related_name="sequences")
    year_be = models.PositiveIntegerField("ปี พ.ศ.")
    last_number = models.PositiveIntegerField("เลขล่าสุด", default=0)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["book", "year_be"], name="uniq_sequence_book_year")]

    def __str__(self):
        return f"{self.book.code} {self.year_be}: {self.last_number}"


class IssuedNumberQuerySet(models.QuerySet):
    def delete(self):
        raise ValidationError("ห้ามลบเลขที่ออกแล้ว ให้ใช้การยกเลิกเลขแทน")


class IssuedNumber(models.Model):
    class Status(models.TextChoices):
        ACTIVE = "ACTIVE", "ใช้งาน"
        VOIDED = "VOIDED", "ยกเลิกแล้ว"

    book = models.ForeignKey(RegisterBook, on_delete=models.PROTECT, related_name="issued_numbers")
    year_be = models.PositiveIntegerField("ปี พ.ศ.")
    running_no = models.PositiveIntegerField("เลขลำดับ")
    display_no = models.CharField("เลขที่", max_length=120)
    subject = models.CharField(
        "เรื่อง", max_length=500, blank=True, help_text="ใช้เมื่อขอเลขโดยยังไม่มีเอกสารในระบบ"
    )
    recipient = models.CharField("ถึง", max_length=300, blank=True)
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.ACTIVE)
    issued_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="issued_numbers"
    )
    issued_at = models.DateTimeField(default=timezone.now)
    voided_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="voided_numbers"
    )
    voided_at = models.DateTimeField(null=True, blank=True)
    void_reason = models.TextField("เหตุผลการยกเลิก", blank=True)

    objects = IssuedNumberQuerySet.as_manager()

    class Meta:
        ordering = ["-year_be", "-running_no"]
        verbose_name = "เลขที่ออกแล้ว"
        verbose_name_plural = "เลขที่ออกแล้ว"
        constraints = [
            models.UniqueConstraint(fields=["book", "year_be", "running_no"], name="uniq_issued_number"),
            # เลขที่ยกเลิกต้องมีเหตุผล ผู้ยกเลิก และเวลาที่ยกเลิกเสมอ (บังคับในระดับฐานข้อมูล)
            models.CheckConstraint(
                condition=models.Q(
                    ("status", "ACTIVE"),
                    models.Q(
                        ("status", "VOIDED"),
                        models.Q(("void_reason", ""), _negated=True),
                        ("voided_by__isnull", False),
                        ("voided_at__isnull", False),
                    ),
                    _connector="OR",
                ),
                name="voided_number_has_reason",
            ),
        ]

    def __str__(self):
        return self.display_no

    @property
    def is_voided(self):
        return self.status == self.Status.VOIDED

    def delete(self, *args, **kwargs):
        raise ValidationError("ห้ามลบเลขที่ออกแล้ว ให้ใช้การยกเลิกเลขแทน")
