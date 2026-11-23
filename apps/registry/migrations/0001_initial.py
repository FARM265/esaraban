import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models

import apps.registry.formatting


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0003_seed_roles"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="RegisterBook",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("code", models.CharField(max_length=20, unique=True, verbose_name="รหัสชุดทะเบียน")),
                ("name_th", models.CharField(max_length=200, verbose_name="ชื่อชุดทะเบียน")),
                (
                    "register_type",
                    models.CharField(
                        choices=[
                            ("RECEIVE", "ทะเบียนรับ"),
                            ("SEND", "ทะเบียนส่ง"),
                            ("INTERNAL", "หนังสือภายใน / บันทึกข้อความ"),
                            ("ORDER", "คำสั่ง"),
                            ("ANNOUNCE", "ประกาศ"),
                        ],
                        max_length=20,
                        verbose_name="ประเภท",
                    ),
                ),
                (
                    "org_code",
                    models.CharField(
                        blank=True,
                        help_text="ใช้แทน {org} ในรูปแบบเลข เช่น ปช XXXX",
                        max_length=50,
                        verbose_name="รหัสหน่วยงาน",
                    ),
                ),
                (
                    "number_format",
                    models.CharField(
                        help_text="ใช้ได้: {org} รหัสหน่วยงาน, {no} เลขลำดับ (เช่น {no:04d} เติม 0 ให้ครบ 4 หลัก), {year} ปี พ.ศ.",
                        max_length=100,
                        validators=[apps.registry.formatting.validate_number_format],
                        verbose_name="รูปแบบเลข",
                    ),
                ),
                ("is_active", models.BooleanField(default=True, verbose_name="ใช้งานอยู่")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        help_text="เว้นว่าง = ใช้ร่วมทั้งสำนักงาน",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="register_books",
                        to="accounts.department",
                        verbose_name="กลุ่มงานเจ้าของ",
                    ),
                ),
            ],
            options={
                "verbose_name": "ชุดทะเบียน",
                "verbose_name_plural": "ชุดทะเบียน",
                "ordering": ["register_type", "code"],
            },
        ),
        migrations.CreateModel(
            name="NumberSequence",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year_be", models.PositiveIntegerField(verbose_name="ปี พ.ศ.")),
                ("last_number", models.PositiveIntegerField(default=0, verbose_name="เลขล่าสุด")),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="sequences",
                        to="registry.registerbook",
                    ),
                ),
            ],
            options={
                "constraints": [models.UniqueConstraint(fields=("book", "year_be"), name="uniq_sequence_book_year")],
            },
        ),
        migrations.CreateModel(
            name="IssuedNumber",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("year_be", models.PositiveIntegerField(verbose_name="ปี พ.ศ.")),
                ("running_no", models.PositiveIntegerField(verbose_name="เลขลำดับ")),
                ("display_no", models.CharField(max_length=120, verbose_name="เลขที่")),
                (
                    "subject",
                    models.CharField(
                        blank=True,
                        help_text="ใช้เมื่อขอเลขโดยยังไม่มีเอกสารในระบบ",
                        max_length=500,
                        verbose_name="เรื่อง",
                    ),
                ),
                ("recipient", models.CharField(blank=True, max_length=300, verbose_name="ถึง")),
                (
                    "status",
                    models.CharField(
                        choices=[("ACTIVE", "ใช้งาน"), ("VOIDED", "ยกเลิกแล้ว")], default="ACTIVE", max_length=10
                    ),
                ),
                ("issued_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("voided_at", models.DateTimeField(blank=True, null=True)),
                ("void_reason", models.TextField(blank=True, verbose_name="เหตุผลการยกเลิก")),
                (
                    "book",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="issued_numbers",
                        to="registry.registerbook",
                    ),
                ),
                (
                    "issued_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="issued_numbers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "voided_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="voided_numbers",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "เลขที่ออกแล้ว",
                "verbose_name_plural": "เลขที่ออกแล้ว",
                "ordering": ["-year_be", "-running_no"],
                "constraints": [
                    models.UniqueConstraint(fields=("book", "year_be", "running_no"), name="uniq_issued_number"),
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
                ],
            },
        ),
    ]
