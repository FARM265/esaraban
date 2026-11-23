"""
การเสนอหนังสือ (workflow)

- WorkflowTemplate / WorkflowStep  เส้นทางการเสนอที่ผู้ดูแลระบบตั้งค่าได้ แยกตามประเภทเอกสาร
- WorkflowInstance  การเสนอเอกสาร 1 ครั้ง เก็บสำเนาขั้นตอน (steps) ไว้ตอนเริ่ม
                    จึงแก้เส้นทางภายหลังได้โดยไม่กระทบเรื่องที่กำลังเดินอยู่
- WorkflowTask      งานแต่ละชิ้น มี 2 แบบ
                    * งานกลาง (role + department) ผู้ที่มีบทบาทนั้นในขอบเขตนั้นคนใดก็รับไปทำได้
                    * งานรายบุคคล (assignee) เช่น งานที่ผู้บริหารสั่งการให้ผู้รับผิดชอบ
- Delegation        มอบหมายปฏิบัติราชการแทนตามช่วงวันที่ บันทึกทั้งผู้มีหน้าที่และผู้ที่กดจริง

ทุกการเปลี่ยนแปลงทำผ่าน apps.workflow.services เท่านั้น
"""
import uuid

from django.conf import settings
from django.db import models
from django.db.models import F, Q
from django.utils import timezone

from apps.core.constants import RoleCode
from apps.documents.models import DocumentKind


class StepKind(models.TextChoices):
    REVIEW = "REVIEW", "พิจารณาเสนอ"
    COMMAND = "COMMAND", "สั่งการ"


class StepScope(models.TextChoices):
    OWNER = "OWNER", "ตามกลุ่มงานเจ้าของเรื่อง"
    ANY = "ANY", "ทั้งสำนักงาน"


class WorkflowTemplate(models.Model):
    name = models.CharField("ชื่อเส้นทาง", max_length=200)
    doc_kind = models.CharField("ใช้กับประเภทเอกสาร", max_length=20, choices=DocumentKind.choices)
    is_active = models.BooleanField("ใช้งานอยู่", default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["doc_kind", "name"]
        verbose_name = "เส้นทางการเสนอ"
        verbose_name_plural = "เส้นทางการเสนอ"

    def __str__(self):
        return self.name

    def snapshot(self):
        return [
            {
                "role": s.role,
                "scope": s.scope,
                "kind": s.kind,
                "sla_hours": s.sla_hours,
                "label": f"{RoleCode(s.role).label}{'' if s.kind == StepKind.REVIEW else 'สั่งการ'}",
            }
            for s in self.steps.order_by("order")
        ]


class WorkflowStep(models.Model):
    template = models.ForeignKey(WorkflowTemplate, on_delete=models.CASCADE, related_name="steps")
    order = models.PositiveSmallIntegerField("ลำดับ")
    role = models.CharField("บทบาทผู้พิจารณา", max_length=20, choices=RoleCode.choices)
    scope = models.CharField("ขอบเขต", max_length=10, choices=StepScope.choices, default=StepScope.OWNER)
    kind = models.CharField("การดำเนินการ", max_length=10, choices=StepKind.choices, default=StepKind.REVIEW)
    sla_hours = models.PositiveSmallIntegerField("ระยะเวลา (ชั่วโมง)", default=24)

    class Meta:
        ordering = ["order"]
        constraints = [models.UniqueConstraint(fields=["template", "order"], name="uniq_step_order")]

    def __str__(self):
        return f"{self.order}. {self.get_role_display()} ({self.get_kind_display()})"


class InstanceStatus(models.TextChoices):
    RUNNING = "RUNNING", "กำลังดำเนินการ"
    DONE = "DONE", "เสร็จสิ้น"
    CANCELLED = "CANCELLED", "ยกเลิก"


class WorkflowInstance(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey("documents.Document", on_delete=models.PROTECT, related_name="workflows")
    template = models.ForeignKey(WorkflowTemplate, null=True, on_delete=models.SET_NULL, related_name="instances")
    template_name = models.CharField(max_length=200)
    steps = models.JSONField(default=list)
    current_step = models.PositiveSmallIntegerField(default=0)
    status = models.CharField(max_length=10, choices=InstanceStatus.choices, default=InstanceStatus.RUNNING)
    started_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    started_at = models.DateTimeField(default=timezone.now)
    finished_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-started_at"]
        constraints = [
            # เอกสาร 1 ฉบับมีการเสนอที่กำลังเดินอยู่ได้ครั้งละ 1 เส้นทางเท่านั้น
            models.UniqueConstraint(
                fields=["document"], condition=Q(status="RUNNING"), name="one_running_workflow_per_document"
            ),
        ]


class TaskKind(models.TextChoices):
    REVIEW = "REVIEW", "พิจารณาเสนอ"
    COMMAND = "COMMAND", "สั่งการ"
    REVISE = "REVISE", "แก้ไขตามที่ส่งกลับ"
    ACT = "ACT", "ดำเนินการตามสั่งการ"


class TaskStatus(models.TextChoices):
    OPEN = "OPEN", "รอดำเนินการ"
    DONE = "DONE", "ดำเนินการแล้ว"
    CANCELLED = "CANCELLED", "ยกเลิก"


class Decision(models.TextChoices):
    FORWARD = "FORWARD", "เสนอต่อ"
    RETURN = "RETURN", "ส่งกลับแก้ไข"
    COMMAND = "COMMAND", "สั่งการ"
    RESUBMIT = "RESUBMIT", "เสนออีกครั้ง"
    CANCEL = "CANCEL", "ยกเลิกการเสนอ"
    COMPLETE = "COMPLETE", "ดำเนินการเสร็จ"


ALLOWED_DECISIONS = {
    TaskKind.REVIEW: [Decision.FORWARD, Decision.RETURN],
    TaskKind.COMMAND: [Decision.COMMAND, Decision.RETURN],
    TaskKind.REVISE: [Decision.RESUBMIT, Decision.CANCEL],
    TaskKind.ACT: [Decision.COMPLETE],
}


class WorkflowTask(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    instance = models.ForeignKey(WorkflowInstance, on_delete=models.PROTECT, related_name="tasks")
    kind = models.CharField(max_length=10, choices=TaskKind.choices)
    step_index = models.PositiveSmallIntegerField(null=True, blank=True)
    # งานกลาง
    role = models.CharField(max_length=20, choices=RoleCode.choices, blank=True)
    department = models.ForeignKey("accounts.Department", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    # งานรายบุคคล
    assignee = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="assigned_tasks"
    )
    status = models.CharField(max_length=10, choices=TaskStatus.choices, default=TaskStatus.OPEN)
    decision = models.CharField(max_length=10, choices=Decision.choices, blank=True)
    comment = models.TextField("ความเห็น", blank=True)
    command_text = models.TextField("ข้อสั่งการ", blank=True)
    due_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(default=timezone.now)
    acted_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="acted_tasks"
    )
    on_behalf_of = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+",
        help_text="ผู้มีหน้าที่ เมื่อผู้กดเป็นผู้ได้รับมอบหมายปฏิบัติราชการแทน",
    )
    acted_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["created_at"]
        indexes = [
            models.Index(fields=["status", "role"], name="task_status_role"),
            models.Index(fields=["assignee", "status"], name="task_assignee_status"),
        ]
        constraints = [
            models.CheckConstraint(
                condition=Q(assignee__isnull=False) | ~Q(role=""), name="task_has_assignee_or_role"
            ),
        ]

    def __str__(self):
        return f"{self.get_kind_display()} ({self.get_status_display()})"

    @property
    def is_overdue(self):
        return self.status == TaskStatus.OPEN and self.due_at is not None and self.due_at < timezone.now()

    @property
    def allowed_decisions(self):
        return ALLOWED_DECISIONS[self.kind]

    @property
    def holder_label(self):
        """ผู้ที่งานนี้รออยู่ สำหรับแสดงในหน้าติดตาม"""
        if self.assignee_id:
            return self.assignee.display_name_th
        scope = self.department.name_th if self.department_id else "ทั้งสำนักงาน"
        return f"{RoleCode(self.role).label} ({scope})"


class DelegationQuerySet(models.QuerySet):
    def active(self, on_date=None):
        today = on_date or timezone.localdate()
        return self.filter(
            start_date__lte=today, end_date__gte=today, revoked_at__isnull=True, delegator__is_active=True
        )


class Delegation(models.Model):
    delegator = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="delegations_given", verbose_name="ผู้มอบหมาย"
    )
    delegate = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="delegations_received",
        verbose_name="ผู้ปฏิบัติราชการแทน",
    )
    start_date = models.DateField("ตั้งแต่วันที่")
    end_date = models.DateField("ถึงวันที่")
    reason = models.CharField("เหตุผล", max_length=300)
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="+")
    created_at = models.DateTimeField(default=timezone.now)
    revoked_at = models.DateTimeField(null=True, blank=True)
    revoked_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, blank=True, on_delete=models.PROTECT, related_name="+"
    )

    objects = DelegationQuerySet.as_manager()

    class Meta:
        ordering = ["-start_date"]
        verbose_name = "การมอบหมายปฏิบัติราชการแทน"
        verbose_name_plural = "การมอบหมายปฏิบัติราชการแทน"
        constraints = [
            models.CheckConstraint(condition=Q(end_date__gte=F("start_date")), name="delegation_valid_range"),
            models.CheckConstraint(condition=~Q(delegator=F("delegate")), name="delegation_not_self"),
        ]

    def __str__(self):
        return f"{self.delegator} → {self.delegate}"

    @property
    def is_active(self):
        today = timezone.localdate()
        return self.revoked_at is None and self.start_date <= today <= self.end_date
