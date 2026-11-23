import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0003_seed_roles"),
        ("registry", "0002_seed_books"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="Document",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("INCOMING", "หนังสือรับ"),
                            ("OUTGOING", "หนังสือส่ง"),
                            ("INTERNAL", "บันทึกข้อความ"),
                            ("ORDER", "คำสั่ง"),
                            ("ANNOUNCE", "ประกาศ"),
                            ("OTHER", "อื่น ๆ"),
                        ],
                        max_length=20,
                        verbose_name="ประเภท",
                    ),
                ),
                ("subject", models.CharField(max_length=500, verbose_name="เรื่อง")),
                ("source_doc_no", models.CharField(blank=True, max_length=100, verbose_name="เลขที่หนังสือต้นทาง")),
                ("source_doc_date", models.DateField(blank=True, null=True, verbose_name="ลงวันที่")),
                ("source_org", models.CharField(blank=True, max_length=300, verbose_name="หน่วยงานต้นทาง")),
                ("recipient", models.CharField(blank=True, max_length=300, verbose_name="เรียน")),
                (
                    "urgency",
                    models.PositiveSmallIntegerField(
                        choices=[(0, "ปกติ"), (1, "ด่วน"), (2, "ด่วนมาก"), (3, "ด่วนที่สุด")],
                        default=0,
                        verbose_name="ความเร่งด่วน",
                    ),
                ),
                (
                    "secrecy",
                    models.PositiveSmallIntegerField(
                        choices=[(0, "ปกติ"), (1, "ลับ"), (2, "ลับมาก"), (3, "ลับที่สุด")],
                        default=0,
                        verbose_name="ชั้นความลับ",
                    ),
                ),
                (
                    "status",
                    models.CharField(
                        choices=[
                            ("REGISTERED", "ลงทะเบียนแล้ว"),
                            ("IN_REVIEW", "อยู่ระหว่างเสนอ"),
                            ("RETURNED", "ส่งกลับแก้ไข"),
                            ("PENDING_SIGNATURE", "รอลงนาม"),
                            ("COMMANDED", "สั่งการแล้ว"),
                            ("IN_PROGRESS", "ดำเนินการ"),
                            ("DONE", "เสร็จสิ้น"),
                            ("ARCHIVED", "จัดเก็บ"),
                            ("CANCELLED", "ยกเลิก"),
                        ],
                        default="REGISTERED",
                        max_length=20,
                        verbose_name="สถานะ",
                    ),
                ),
                ("due_date", models.DateField(blank=True, null=True, verbose_name="กำหนดเสร็จ")),
                ("note", models.TextField(blank=True, verbose_name="หมายเหตุ")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("updated_at", models.DateTimeField(auto_now=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="created_documents",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "owner_department",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="documents",
                        to="accounts.department",
                        verbose_name="กลุ่มงานเจ้าของเรื่อง",
                    ),
                ),
                (
                    "registration",
                    models.OneToOneField(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="document",
                        to="registry.issuednumber",
                        verbose_name="เลขทะเบียน",
                    ),
                ),
            ],
            options={
                "verbose_name": "เอกสาร",
                "verbose_name_plural": "เอกสาร",
                "ordering": ["-created_at"],
                "indexes": [
                    models.Index(fields=["status", "owner_department"], name="doc_status_dept"),
                    models.Index(fields=["kind", "created_at"], name="doc_kind_created"),
                    models.Index(fields=["due_date"], name="doc_due_date"),
                ],
            },
        ),
        migrations.CreateModel(
            name="Attachment",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("original_name", models.CharField(max_length=255, verbose_name="ชื่อไฟล์")),
                ("storage_key", models.CharField(editable=False, max_length=255, unique=True)),
                ("size", models.PositiveIntegerField(verbose_name="ขนาด (ไบต์)")),
                ("sha256", models.CharField(editable=False, max_length=64)),
                ("content_type", models.CharField(default="application/pdf", max_length=100)),
                ("page_count", models.PositiveIntegerField(blank=True, null=True)),
                ("is_main", models.BooleanField(default=False, verbose_name="ไฟล์หลัก")),
                ("version", models.PositiveIntegerField(default=1)),
                ("uploaded_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="attachments",
                        to="documents.document",
                    ),
                ),
                (
                    "uploaded_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "ไฟล์แนบ",
                "verbose_name_plural": "ไฟล์แนบ",
                "ordering": ["-is_main", "uploaded_at"],
            },
        ),
        migrations.CreateModel(
            name="DocumentEvent",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                (
                    "action",
                    models.CharField(
                        choices=[
                            ("REGISTERED", "ลงทะเบียน"),
                            ("UPDATED", "แก้ไขข้อมูล"),
                            ("FILE_ADDED", "เพิ่มไฟล์"),
                            ("VIEWED", "เปิดดูไฟล์"),
                            ("DOWNLOADED", "ดาวน์โหลดไฟล์"),
                            ("CANCELLED", "ยกเลิก"),
                        ],
                        max_length=20,
                    ),
                ),
                ("detail", models.JSONField(blank=True, default=dict)),
                ("ip_address", models.GenericIPAddressField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                (
                    "actor",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="events",
                        to="documents.document",
                    ),
                ),
            ],
            options={
                "ordering": ["-created_at"],
                "indexes": [models.Index(fields=["document", "created_at"], name="docevent_doc_time")],
            },
        ),
    ]
