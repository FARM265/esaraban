"""
ตรรกะการเสนอหนังสือ

ใครทำงานชิ้นไหนได้ (can_act):
- งานรายบุคคล: ผู้ได้รับมอบหมาย (assignee)
- งานกลาง: ผู้มีบทบาทตรงกับงาน และขอบเขตบทบาทครอบคลุมกลุ่มงานของงาน
  (งานที่ไม่ระบุกลุ่มงาน = ผู้มีบทบาทนั้นคนใดก็ได้)
- ผู้ได้รับมอบหมายปฏิบัติราชการแทน ทำงานของผู้มอบหมายได้ในช่วงวันที่ที่กำหนด
  ระบบบันทึกทั้งผู้กด (acted_by) และผู้มีหน้าที่ (on_behalf_of)
- ทุกกรณี ชั้นความลับของเอกสารต้องไม่เกินระดับสิทธิ์ของผู้กด (และของผู้มอบหมาย)
"""
from datetime import datetime, time, timedelta

from django.contrib.auth import get_user_model
from django.core.exceptions import PermissionDenied, ValidationError
from django.db import transaction
from django.db.models import Q
from django.utils import timezone

from apps.accounts.models import UserRole, department_with_descendants
from apps.accounts.permissions import active_roles
from apps.core.constants import RoleCode
from apps.documents.models import Document, DocumentEvent, DocumentStatus
from apps.documents.services import log_event

from .models import (
    ALLOWED_DECISIONS,
    Decision,
    Delegation,
    InstanceStatus,
    StepScope,
    TaskKind,
    TaskStatus,
    WorkflowInstance,
    WorkflowTask,
)

User = get_user_model()

# ---------------------------------------------------------------------------
# ใครทำงานได้
# ---------------------------------------------------------------------------


def active_delegators(user):
    if not getattr(user, "is_authenticated", False):
        return []
    return list(
        User.objects.filter(
            pk__in=Delegation.objects.active().filter(delegate=user).values("delegator"), is_active=True
        )
    )


def _pool_q(person):
    """เงื่อนไขของงานกลางที่ person มีบทบาทครอบคลุม (None = ไม่มีเลย)"""
    q = None
    for assignment in active_roles(person):
        code = assignment.role.code
        if assignment.department_id is None:
            part = Q(role=code)
        else:
            covered = department_with_descendants({assignment.department_id})
            part = Q(role=code, department_id__in=covered) | Q(role=code, department__isnull=True)
        q = part if q is None else q | part
    return q


def _person_q(person):
    q = Q(assignee=person)
    pool = _pool_q(person)
    if pool is not None:
        q |= Q(assignee__isnull=True) & pool
    return q & Q(instance__document__secrecy__lte=person.clearance_level)


def _open_tasks():
    return WorkflowTask.objects.filter(status=TaskStatus.OPEN, instance__status=InstanceStatus.RUNNING)


def actionable_tasks(user):
    """งานที่ user ทำได้ตอนนี้ (รวมงานที่ทำแทนผู้มอบหมาย)"""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return WorkflowTask.objects.none()
    q = _person_q(user)
    for delegator in active_delegators(user):
        q |= _person_q(delegator) & Q(instance__document__secrecy__lte=user.clearance_level)
    return _open_tasks().filter(q).distinct()


def can_act(user, task):
    """คืนค่า (ทำได้หรือไม่, ผู้มีหน้าที่ที่ทำแทน หรือ None ถ้าทำในนามตนเอง)"""
    if not getattr(user, "is_authenticated", False) or not user.is_active:
        return False, None
    base = _open_tasks().filter(pk=task.pk)
    if base.filter(_person_q(user)).exists():
        return True, None
    for delegator in active_delegators(user):
        if base.filter(_person_q(delegator), instance__document__secrecy__lte=user.clearance_level).exists():
            return True, delegator
    return False, None


def involved_document_ids(user):
    """เอกสารที่ผู้ใช้มีงานอยู่ ได้รับมอบหมาย หรือเคยดำเนินการใน workflow"""
    if not getattr(user, "is_authenticated", False):
        return Document.objects.none().values("pk")
    past = WorkflowTask.objects.filter(Q(assignee=user) | Q(acted_by=user)).values("instance__document")
    current = actionable_tasks(user).values("instance__document")
    return Document.objects.filter(Q(pk__in=past) | Q(pk__in=current)).values("pk")


def eligible_users(role, department, secrecy):
    """ผู้ใช้ที่ทำงานกลางของบทบาทนี้ได้ (ใช้ตรวจก่อนเริ่มเสนอว่ามีผู้รับงานจริง)"""
    assignments = UserRole.objects.active().filter(role__code=role, user__is_active=True)
    if department is not None:
        assignments = assignments.filter(
            Q(department__isnull=True) | Q(department_id__in=department.ancestor_ids())
        )
    return User.objects.filter(pk__in=assignments.values("user"), clearance_level__gte=secrecy)


# ---------------------------------------------------------------------------
# เริ่มเสนอ
# ---------------------------------------------------------------------------


def running_instance(document):
    return document.workflows.filter(status=InstanceStatus.RUNNING).first()


def _step_department(instance, step):
    return instance.document.owner_department if step["scope"] == StepScope.OWNER else None


TASK_TITLES = {
    TaskKind.REVIEW: "มีเรื่องรอพิจารณา",
    TaskKind.COMMAND: "มีเรื่องรอสั่งการ/ลงนาม",
    TaskKind.REVISE: "เรื่องถูกส่งกลับแก้ไข",
    TaskKind.ACT: "ได้รับมอบหมายให้ดำเนินการ",
}


def _document_label(document):
    number = document.registration.display_no if document.registration_id else "ร่าง"
    return f"{number} {document.subject}"


def _notify_new_task(task, actor):
    """แจ้งผู้ที่ต้องทำงานนี้: งานที่มอบให้คนเดียวแจ้งคนนั้น งานกลางแจ้งทุกคนที่มีบทบาทตรงกัน"""
    from apps.notifications.services import notify

    document = task.instance.document
    users = [task.assignee] if task.assignee_id else eligible_users(task.role, task.department, document.secrecy)
    body = _document_label(document)
    if task.kind == TaskKind.REVISE and task.instance.tasks.filter(status=TaskStatus.DONE).exists():
        last = task.instance.tasks.filter(status=TaskStatus.DONE).order_by("-acted_at").first()
        body = f"{body} · {last.comment}" if last and last.comment else body
    if task.kind == TaskKind.ACT and task.command_text:
        body = f"{body} · ข้อสั่งการ: {task.command_text}"
    notify(users, TASK_TITLES[task.kind], body=body, document=document, exclude=actor)


def _notify_finished(instance, actor):
    from apps.notifications.services import notify

    notify([instance.started_by], "เรื่องที่ท่านเสนอดำเนินการเสร็จสิ้น", body=_document_label(instance.document),
           document=instance.document, exclude=actor)


def _create_task(actor, **fields):
    task = WorkflowTask.objects.create(**fields)
    _notify_new_task(task, actor)
    return task


def _open_step(instance, index, actor=None):
    step = instance.steps[index]
    instance.current_step = index
    instance.save(update_fields=["current_step"])
    return _create_task(
        actor,
        instance=instance,
        kind=step["kind"],
        step_index=index,
        role=step["role"],
        department=_step_department(instance, step),
        due_at=timezone.now() + timedelta(hours=step["sla_hours"]),
    )


STARTABLE_STATUSES = (DocumentStatus.REGISTERED, DocumentStatus.DRAFT)


def _status_before_review(document):
    """สถานะเมื่อยกเลิกการเสนอ: หนังสือที่ยังไม่ออกเลขกลับเป็นร่าง"""
    if document.registration_id is None and document.kind != "INCOMING":
        return DocumentStatus.DRAFT
    return DocumentStatus.REGISTERED


def _set_status(document, status):
    document.status = status
    document.save(update_fields=["status", "updated_at"])


@transaction.atomic
def start_workflow(document, template, user, ip=None, comment=""):
    document = Document.objects.select_for_update().get(pk=document.pk)
    if running_instance(document):
        raise ValidationError("เอกสารนี้กำลังอยู่ระหว่างการเสนอแล้ว")
    if document.status not in STARTABLE_STATUSES:
        raise ValidationError(f"เริ่มเสนอไม่ได้ เพราะเอกสารมีสถานะ {document.get_status_display()}")
    if not template.is_active or template.doc_kind != document.kind:
        raise ValidationError("เส้นทางนี้ใช้กับเอกสารประเภทนี้ไม่ได้")
    steps = template.snapshot()
    if not steps:
        raise ValidationError("เส้นทางนี้ยังไม่มีขั้นตอน")
    for step in steps:
        if step["scope"] == StepScope.OWNER and document.owner_department is None:
            raise ValidationError("ต้องระบุกลุ่มงานเจ้าของเรื่องก่อนเสนอตามเส้นทางนี้")
        department = document.owner_department if step["scope"] == StepScope.OWNER else None
        if not eligible_users(step["role"], department, document.secrecy).exists():
            where = f" ที่ดูแล{department}" if department else ""
            raise ValidationError(
                f"ไม่มีผู้ใช้ที่มีบทบาท{RoleCode(step['role']).label}{where} และมีสิทธิ์ชั้นความลับเพียงพอ "
                "กรุณาให้ผู้ดูแลระบบกำหนดบทบาทก่อน"
            )
    instance = WorkflowInstance.objects.create(
        document=document, template=template, template_name=template.name, steps=steps, started_by=user
    )
    _open_step(instance, 0, user)
    _set_status(document, DocumentStatus.IN_REVIEW)
    log_event(document, user, DocumentEvent.Action.WORKFLOW_STARTED, ip, route=template.name, comment=comment)
    return instance


# ---------------------------------------------------------------------------
# ดำเนินการกับงาน
# ---------------------------------------------------------------------------

EVENT_FOR = {
    Decision.FORWARD: DocumentEvent.Action.FORWARDED,
    Decision.RETURN: DocumentEvent.Action.RETURNED,
    Decision.RESUBMIT: DocumentEvent.Action.RESUBMITTED,
    Decision.COMMAND: DocumentEvent.Action.COMMANDED,
    Decision.COMPLETE: DocumentEvent.Action.COMPLETED,
    Decision.CANCEL: DocumentEvent.Action.WORKFLOW_CANCELLED,
}


def _end_of_day(day):
    return timezone.make_aware(datetime.combine(day, time(16, 30)))  # เวลาเลิกราชการ


@transaction.atomic
def act(task, user, decision, *, comment="", command_text="", assignees=(), due_date=None, ip=None):
    task = WorkflowTask.objects.select_for_update().get(pk=task.pk)
    if task.status != TaskStatus.OPEN:
        raise ValidationError("งานนี้ถูกดำเนินการไปแล้ว")
    allowed, on_behalf_of = can_act(user, task)
    if not allowed:
        raise PermissionDenied
    if decision not in ALLOWED_DECISIONS[task.kind]:
        raise ValidationError("การดำเนินการนี้ใช้กับงานนี้ไม่ได้")
    comment = (comment or "").strip()
    command_text = (command_text or "").strip()
    if decision in (Decision.RETURN, Decision.CANCEL) and not comment:
        raise ValidationError("กรุณาระบุเหตุผลหรือสิ่งที่ต้องแก้ไข")
    if decision == Decision.COMMAND and not command_text:
        raise ValidationError("กรุณาระบุข้อสั่งการ")

    instance = WorkflowInstance.objects.select_for_update().get(pk=task.instance_id)
    document = Document.objects.select_for_update().get(pk=instance.document_id)

    assignees = list(assignees)
    for person in assignees:
        if not person.is_active or person.clearance_level < document.secrecy:
            raise ValidationError(f"{person} ไม่มีสิทธิ์รับเรื่องที่มีชั้นความลับระดับนี้")

    task.status = TaskStatus.DONE
    task.decision = decision
    task.comment = comment
    task.command_text = command_text
    task.acted_by = user
    task.on_behalf_of = on_behalf_of
    task.acted_at = timezone.now()
    task.save()

    if decision == Decision.FORWARD:
        _open_step(instance, task.step_index + 1, user)
        _set_status(document, DocumentStatus.IN_REVIEW)
    elif decision == Decision.RETURN:
        if task.step_index:
            _open_step(instance, task.step_index - 1, user)
        else:
            _create_task(user, instance=instance, kind=TaskKind.REVISE, assignee=instance.started_by)
        _set_status(document, DocumentStatus.RETURNED)
    elif decision == Decision.RESUBMIT:
        _open_step(instance, 0, user)
        _set_status(document, DocumentStatus.IN_REVIEW)
    elif decision == Decision.CANCEL:
        _finish(instance, InstanceStatus.CANCELLED)
        _set_status(document, _status_before_review(document))
    elif decision == Decision.COMMAND:
        due_at = _end_of_day(due_date) if due_date else None
        for person in assignees:
            _create_task(
                user, instance=instance, kind=TaskKind.ACT, assignee=person, command_text=command_text, due_at=due_at
            )
        if due_date:
            document.due_date = due_date
            document.save(update_fields=["due_date", "updated_at"])
        if assignees:
            _set_status(document, DocumentStatus.COMMANDED)
        else:  # สั่งการโดยไม่มอบผู้รับผิดชอบ เช่น "ทราบ" หรือ "เก็บเข้าแฟ้ม"
            _finish(instance, InstanceStatus.DONE)
            _set_status(document, DocumentStatus.DONE)
            _notify_finished(instance, user)
    elif decision == Decision.COMPLETE:
        if not instance.tasks.filter(status=TaskStatus.OPEN).exists():
            _finish(instance, InstanceStatus.DONE)
            _set_status(document, DocumentStatus.DONE)
            _notify_finished(instance, user)
        else:
            _set_status(document, DocumentStatus.IN_PROGRESS)

    log_event(
        document, user, EVENT_FOR[decision], ip,
        comment=comment or command_text,
        on_behalf_of=str(on_behalf_of) if on_behalf_of else "",
        assignees=[str(p) for p in assignees],
    )
    return task


def _finish(instance, status):
    instance.status = status
    instance.finished_at = timezone.now()
    instance.save(update_fields=["status", "finished_at"])


# ---------------------------------------------------------------------------
# มอบหมายปฏิบัติราชการแทน
# ---------------------------------------------------------------------------


def create_delegation(*, delegator, delegate, start_date, end_date, reason, created_by):
    if delegator == delegate:
        raise ValidationError("มอบหมายให้ตัวเองไม่ได้")
    if end_date < start_date:
        raise ValidationError("วันสิ้นสุดต้องไม่ก่อนวันเริ่มต้น")
    if not delegate.is_active:
        raise ValidationError("ผู้ปฏิบัติราชการแทนถูกระงับบัญชีอยู่")
    from apps.audit import services as audit

    delegation = Delegation.objects.create(
        delegator=delegator, delegate=delegate, start_date=start_date, end_date=end_date,
        reason=reason.strip(), created_by=created_by,
    )
    audit.record(
        "USER", "DELEGATION_CREATED", f"มอบหมาย {delegate} ปฏิบัติราชการแทน {delegator}",
        actor=created_by, target=delegation, start=start_date, end=end_date, reason=delegation.reason,
    )
    return delegation


def revoke_delegation(delegation, user):
    if delegation.revoked_at:
        return delegation
    delegation.revoked_at = timezone.now()
    delegation.revoked_by = user
    delegation.save(update_fields=["revoked_at", "revoked_by"])
    from apps.audit import services as audit

    audit.record("USER", "DELEGATION_REVOKED", f"ยุติการมอบหมาย {delegation.delegate} แทน {delegation.delegator}",
                 actor=user, target=delegation)
    return delegation
