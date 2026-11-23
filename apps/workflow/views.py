from django.contrib import messages
from django.core.exceptions import ValidationError
from django.db import transaction
from django.db.models import Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.accounts.permissions import capability_required, has_capability
from apps.accounts.security import client_ip
from apps.documents import access
from apps.documents.models import Document

from . import services
from .forms import ActionForm, DelegationForm, StartForm, StepFormSet, WorkflowTemplateForm
from .models import Delegation, WorkflowStep, WorkflowTask, WorkflowTemplate
from .panel import can_start


def _errors(exc):
    return " ".join(exc.messages) if hasattr(exc, "messages") else str(exc)


def my_tasks(request):
    tasks = (
        services.actionable_tasks(request.user)
        .select_related("instance__document__registration", "instance__document__owner_department", "assignee")
        .order_by("due_at", "created_at")
    )
    delegators = services.active_delegators(request.user)
    return render(request, "workflow/my_tasks.html", {"tasks": tasks, "delegators": delegators})


@require_POST
def start(request, document_id):
    document = get_object_or_404(Document, pk=document_id)
    if not access.can_view(request.user, document):
        raise Http404
    if not can_start(request.user, document):
        messages.error(request, "ท่านเริ่มเสนอเอกสารนี้ไม่ได้")
        return redirect("documents:detail", pk=document.pk)
    form = StartForm(request.POST, document=document)
    if form.is_valid():
        try:
            services.start_workflow(
                document, form.cleaned_data["template"], request.user, client_ip(request), form.cleaned_data["comment"]
            )
            messages.success(request, f"เริ่มเสนอตามเส้นทาง {form.cleaned_data['template']} แล้ว")
        except ValidationError as exc:
            messages.error(request, _errors(exc))
    else:
        messages.error(request, "กรุณาเลือกเส้นทางการเสนอ")
    return redirect("documents:detail", pk=document.pk)


@require_POST
def act(request, task_id):
    task = get_object_or_404(WorkflowTask.objects.select_related("instance__document"), pk=task_id)
    document = task.instance.document
    allowed, _ = services.can_act(request.user, task)
    if not allowed:
        # ไม่บอกรายละเอียดถ้าผู้ใช้มองไม่เห็นเอกสาร
        if not access.can_view(request.user, document):
            raise Http404
        messages.error(request, "ท่านไม่ได้เป็นผู้รับผิดชอบงานนี้ หรืองานนี้ถูกดำเนินการไปแล้ว")
        return redirect("documents:detail", pk=document.pk)
    form = ActionForm(request.POST, document=document)
    if not form.is_valid():
        errors = "; ".join(e for errs in form.errors.values() for e in errs)
        messages.error(request, f"ยังไม่ได้บันทึก: {errors}")
        return redirect("documents:detail", pk=document.pk)
    data = form.cleaned_data
    try:
        services.act(
            task, request.user, data["decision"],
            comment=data["comment"], command_text=data["command_text"],
            assignees=data["assignees"], due_date=data["due_date"], ip=client_ip(request),
        )
        messages.success(request, "บันทึกการดำเนินการแล้ว")
    except ValidationError as exc:
        messages.error(request, _errors(exc))
    # หลังส่งต่อ ผู้ใช้อาจมองไม่เห็นเอกสารแล้ว จึงกลับไปหน้างานรอดำเนินการถ้าจำเป็น
    if access.can_view(request.user, document):
        return redirect("documents:detail", pk=document.pk)
    return redirect("workflow:my_tasks")


# ---------------------------------------------------------------------------
# ตั้งค่าเส้นทาง
# ---------------------------------------------------------------------------


@capability_required("manage_workflows")
def template_list(request):
    templates = WorkflowTemplate.objects.prefetch_related("steps")
    return render(request, "workflow/template_list.html", {"templates": templates})


@capability_required("manage_workflows")
def template_edit(request, pk=None):
    instance = get_object_or_404(WorkflowTemplate, pk=pk) if pk else WorkflowTemplate()
    form = WorkflowTemplateForm(request.POST or None, instance=instance)
    formset = StepFormSet(request.POST or None, instance=instance, prefix="steps")
    if request.method == "POST":
        if form.is_valid() and formset.is_valid():
            with transaction.atomic():
                template = form.save()
                formset.instance = template
                steps = formset.save(commit=False)  # เฉพาะขั้นตอนที่เพิ่มหรือแก้ไข
                for obj in formset.deleted_objects:
                    obj.delete()
                # ย้ายลำดับชั่วคราวก่อน กันชน unique (template, order) เมื่อสลับลำดับกัน
                for i, step in enumerate(s for s in steps if s.pk):
                    WorkflowStep.objects.filter(pk=step.pk).update(order=1000 + i)
                for step in steps:
                    step.template = template
                    step.save()
            from apps.audit import services as audit

            audit.record("SETTINGS", "WORKFLOW_TEMPLATE_SAVED", f"บันทึกเส้นทางการเสนอ {template.name}",
                         actor=request.user, target=template, ip=client_ip(request))
            messages.success(request, f"บันทึกเส้นทาง {template.name} แล้ว เรื่องที่กำลังเสนออยู่ใช้เส้นทางเดิมต่อไป")
            return redirect("workflow:template_list")
        messages.error(request, "ยังไม่ได้บันทึก กรุณาแก้ไขข้อมูลที่แจ้งไว้")
    return render(
        request, "workflow/template_form.html", {"form": form, "formset": formset, "instance": instance if pk else None}
    )


# ---------------------------------------------------------------------------
# มอบหมายปฏิบัติราชการแทน
# ---------------------------------------------------------------------------


def delegations(request):
    can_manage_all = has_capability(request.user, "manage_users")
    form = DelegationForm(request.POST or None, user=request.user, can_manage_all=can_manage_all)
    if request.method == "POST":
        if form.is_valid():
            try:
                services.create_delegation(created_by=request.user, **form.cleaned_data)
                messages.success(request, "บันทึกการมอบหมายแล้ว")
                return redirect("workflow:delegations")
            except ValidationError as exc:
                messages.error(request, _errors(exc))
        else:
            messages.error(request, "ยังไม่ได้บันทึก กรุณาแก้ไขข้อมูลที่แจ้งไว้")
    qs = Delegation.objects.select_related("delegator", "delegate", "created_by")
    if not can_manage_all:
        qs = qs.filter(Q(delegator=request.user) | Q(delegate=request.user))
    return render(
        request,
        "workflow/delegations.html",
        {"form": form, "delegations": qs[:100], "can_manage_all": can_manage_all, "today": timezone.localdate()},
    )


@require_POST
def delegation_revoke(request, pk):
    delegation = get_object_or_404(Delegation, pk=pk)
    if not (delegation.delegator == request.user or has_capability(request.user, "manage_users")):
        raise Http404
    services.revoke_delegation(delegation, request.user)
    messages.success(request, "ยุติการมอบหมายแล้ว")
    return redirect("workflow:delegations")
