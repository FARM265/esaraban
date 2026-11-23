import uuid

import django.db.models.deletion
import django.utils.timezone
from django.conf import settings
from django.db import migrations, models
from django.db.models import F, Q

ROLE_CHOICES = [
    ("ADMIN", "ผู้ดูแลระบบ"),
    ("EXECUTIVE", "ผู้บริหาร"),
    ("HEAD", "หัวหน้ากลุ่มงาน"),
    ("CLERK", "เจ้าหน้าที่สารบรรณ"),
    ("STAFF", "เจ้าหน้าที่ทั่วไป"),
    ("AUDITOR", "ผู้ตรวจสอบ"),
]
KIND_CHOICES = [
    ("INCOMING", "หนังสือรับ"),
    ("OUTGOING", "หนังสือส่ง"),
    ("INTERNAL", "บันทึกข้อความ"),
    ("ORDER", "คำสั่ง"),
    ("ANNOUNCE", "ประกาศ"),
    ("OTHER", "อื่น ๆ"),
]


class Migration(migrations.Migration):

    initial = True

    dependencies = [
        ("accounts", "0003_seed_roles"),
        ("documents", "0001_initial"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="WorkflowTemplate",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("name", models.CharField(max_length=200, verbose_name="ชื่อเส้นทาง")),
                ("doc_kind", models.CharField(choices=KIND_CHOICES, max_length=20, verbose_name="ใช้กับประเภทเอกสาร")),
                ("is_active", models.BooleanField(default=True, verbose_name="ใช้งานอยู่")),
                ("created_at", models.DateTimeField(auto_now_add=True)),
            ],
            options={
                "verbose_name": "เส้นทางการเสนอ",
                "verbose_name_plural": "เส้นทางการเสนอ",
                "ordering": ["doc_kind", "name"],
            },
        ),
        migrations.CreateModel(
            name="WorkflowStep",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("order", models.PositiveSmallIntegerField(verbose_name="ลำดับ")),
                ("role", models.CharField(choices=ROLE_CHOICES, max_length=20, verbose_name="บทบาทผู้พิจารณา")),
                (
                    "scope",
                    models.CharField(
                        choices=[("OWNER", "ตามกลุ่มงานเจ้าของเรื่อง"), ("ANY", "ทั้งสำนักงาน")],
                        default="OWNER",
                        max_length=10,
                        verbose_name="ขอบเขต",
                    ),
                ),
                (
                    "kind",
                    models.CharField(
                        choices=[("REVIEW", "พิจารณาเสนอ"), ("COMMAND", "สั่งการ")],
                        default="REVIEW",
                        max_length=10,
                        verbose_name="การดำเนินการ",
                    ),
                ),
                ("sla_hours", models.PositiveSmallIntegerField(default=24, verbose_name="ระยะเวลา (ชั่วโมง)")),
                (
                    "template",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.CASCADE, related_name="steps", to="workflow.workflowtemplate"
                    ),
                ),
            ],
            options={
                "ordering": ["order"],
                "constraints": [models.UniqueConstraint(fields=("template", "order"), name="uniq_step_order")],
            },
        ),
        migrations.CreateModel(
            name="WorkflowInstance",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ("template_name", models.CharField(max_length=200)),
                ("steps", models.JSONField(default=list)),
                ("current_step", models.PositiveSmallIntegerField(default=0)),
                (
                    "status",
                    models.CharField(
                        choices=[("RUNNING", "กำลังดำเนินการ"), ("DONE", "เสร็จสิ้น"), ("CANCELLED", "ยกเลิก")],
                        default="RUNNING",
                        max_length=10,
                    ),
                ),
                ("started_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("finished_at", models.DateTimeField(blank=True, null=True)),
                (
                    "document",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="workflows", to="documents.document"
                    ),
                ),
                (
                    "started_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "template",
                    models.ForeignKey(
                        null=True,
                        on_delete=django.db.models.deletion.SET_NULL,
                        related_name="instances",
                        to="workflow.workflowtemplate",
                    ),
                ),
            ],
            options={
                "ordering": ["-started_at"],
                "constraints": [
                    models.UniqueConstraint(
                        condition=Q(status="RUNNING"), fields=("document",), name="one_running_workflow_per_document"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="WorkflowTask",
            fields=[
                ("id", models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                (
                    "kind",
                    models.CharField(
                        choices=[
                            ("REVIEW", "พิจารณาเสนอ"),
                            ("COMMAND", "สั่งการ"),
                            ("REVISE", "แก้ไขตามที่ส่งกลับ"),
                            ("ACT", "ดำเนินการตามสั่งการ"),
                        ],
                        max_length=10,
                    ),
                ),
                ("step_index", models.PositiveSmallIntegerField(blank=True, null=True)),
                ("role", models.CharField(blank=True, choices=ROLE_CHOICES, max_length=20)),
                (
                    "status",
                    models.CharField(
                        choices=[("OPEN", "รอดำเนินการ"), ("DONE", "ดำเนินการแล้ว"), ("CANCELLED", "ยกเลิก")],
                        default="OPEN",
                        max_length=10,
                    ),
                ),
                (
                    "decision",
                    models.CharField(
                        blank=True,
                        choices=[
                            ("FORWARD", "เสนอต่อ"),
                            ("RETURN", "ส่งกลับแก้ไข"),
                            ("COMMAND", "สั่งการ"),
                            ("RESUBMIT", "เสนออีกครั้ง"),
                            ("CANCEL", "ยกเลิกการเสนอ"),
                            ("COMPLETE", "ดำเนินการเสร็จ"),
                        ],
                        max_length=10,
                    ),
                ),
                ("comment", models.TextField(blank=True, verbose_name="ความเห็น")),
                ("command_text", models.TextField(blank=True, verbose_name="ข้อสั่งการ")),
                ("due_at", models.DateTimeField(blank=True, null=True)),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("acted_at", models.DateTimeField(blank=True, null=True)),
                (
                    "acted_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="acted_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "assignee",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="assigned_tasks",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
                (
                    "department",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to="accounts.department",
                    ),
                ),
                (
                    "instance",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="tasks", to="workflow.workflowinstance"
                    ),
                ),
                (
                    "on_behalf_of",
                    models.ForeignKey(
                        blank=True,
                        help_text="ผู้มีหน้าที่ เมื่อผู้กดเป็นผู้ได้รับมอบหมายปฏิบัติราชการแทน",
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "ordering": ["created_at"],
                "indexes": [
                    models.Index(fields=["status", "role"], name="task_status_role"),
                    models.Index(fields=["assignee", "status"], name="task_assignee_status"),
                ],
                "constraints": [
                    models.CheckConstraint(
                        condition=Q(assignee__isnull=False) | ~Q(role=""), name="task_has_assignee_or_role"
                    )
                ],
            },
        ),
        migrations.CreateModel(
            name="Delegation",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("start_date", models.DateField(verbose_name="ตั้งแต่วันที่")),
                ("end_date", models.DateField(verbose_name="ถึงวันที่")),
                ("reason", models.CharField(max_length=300, verbose_name="เหตุผล")),
                ("created_at", models.DateTimeField(default=django.utils.timezone.now)),
                ("revoked_at", models.DateTimeField(blank=True, null=True)),
                (
                    "created_by",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT, related_name="+", to=settings.AUTH_USER_MODEL
                    ),
                ),
                (
                    "delegate",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="delegations_received",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="ผู้ปฏิบัติราชการแทน",
                    ),
                ),
                (
                    "delegator",
                    models.ForeignKey(
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="delegations_given",
                        to=settings.AUTH_USER_MODEL,
                        verbose_name="ผู้มอบหมาย",
                    ),
                ),
                (
                    "revoked_by",
                    models.ForeignKey(
                        blank=True,
                        null=True,
                        on_delete=django.db.models.deletion.PROTECT,
                        related_name="+",
                        to=settings.AUTH_USER_MODEL,
                    ),
                ),
            ],
            options={
                "verbose_name": "การมอบหมายปฏิบัติราชการแทน",
                "verbose_name_plural": "การมอบหมายปฏิบัติราชการแทน",
                "ordering": ["-start_date"],
                "constraints": [
                    models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="delegation_valid_range"),
                    models.CheckConstraint(condition=~Q(delegator=F("delegate")), name="delegation_not_self"),
                ],
            },
        ),
    ]
