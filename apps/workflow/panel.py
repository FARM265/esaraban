"""ข้อมูลแผง "การเสนอ" ในหน้ารายละเอียดเอกสาร"""
from apps.accounts.permissions import has_capability
from apps.documents import access

from . import services
from .forms import ActionForm, StartForm
from .models import InstanceStatus, TaskKind, TaskStatus, WorkflowTask


def can_start(user, document):
    if document.status not in services.STARTABLE_STATUSES or services.running_instance(document) is not None:
        return False
    if not access.can_view(user, document):
        return False
    if has_capability(user, "register_documents", document.owner_department):
        return True
    # ผู้ร่างหนังสือจากแม่แบบ เสนอร่างของตนเองได้
    from apps.letters.services import is_letter

    return is_letter(document) and (
        document.created_by_id == user.pk or has_capability(user, "create_documents", document.owner_department)
    )


def _stepper(instance, document):
    if instance is None:
        return []
    running = instance.status == InstanceStatus.RUNNING
    done_all = instance.status == InstanceStatus.DONE
    has_revise = running and instance.tasks.filter(kind=TaskKind.REVISE, status=TaskStatus.OPEN).exists()
    has_act = instance.tasks.filter(kind=TaskKind.ACT).exists()
    act_open = running and instance.tasks.filter(kind=TaskKind.ACT, status=TaskStatus.OPEN).exists()

    items = [{"label": "สารบรรณลงรับและเสนอ", "state": "current" if has_revise else "done"}]
    for index, step in enumerate(instance.steps):
        if done_all or (running and (index < instance.current_step or act_open)):
            state = "done"
        elif running and index == instance.current_step and not has_revise and not act_open:
            state = "current"
        else:
            state = "todo"
        items.append({"label": step["label"], "state": state})
    if done_all:
        items.append({"label": "ผู้รับผิดชอบดำเนินการ" if has_act else "จบเรื่อง", "state": "done"})
    else:
        items.append({"label": "ผู้รับผิดชอบดำเนินการ", "state": "current" if act_open else "todo"})
    for n, item in enumerate(items, start=1):
        item["n"] = n
    return items


def context_for(user, document):
    instance = document.workflows.order_by("-started_at").first()
    running = instance if instance and instance.status == InstanceStatus.RUNNING else None

    my_tasks = []
    open_tasks = []
    if running:
        open_tasks = list(
            running.tasks.filter(status=TaskStatus.OPEN).select_related("assignee", "department")
        )
        for task in open_tasks:
            allowed, on_behalf_of = services.can_act(user, task)
            if allowed:
                my_tasks.append({"task": task, "on_behalf_of": on_behalf_of})

    history = (
        WorkflowTask.objects.filter(instance__document=document, status=TaskStatus.DONE)
        .select_related("acted_by", "on_behalf_of", "assignee")
        .order_by("-acted_at")
    )

    return {
        "wf_instance": instance,
        "wf_running": running,
        "wf_steps": _stepper(instance, document),
        "wf_open_tasks": open_tasks,
        "wf_my_tasks": my_tasks,
        "wf_action_form": ActionForm(document=document) if my_tasks else None,
        "wf_history": history,
        "wf_start_form": StartForm(document=document) if can_start(user, document) else None,
    }
